"""A separate, deterministic release type for the isolated synthetic preview."""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

from .html_updater import digest
from .schemas import WebsiteProposal

REPOSITORY = 'lee-jr11/prymage-staging-sandbox'


def candidate(baseline: str, script: str) -> str:
    if baseline.count('<head>') != 1 or baseline.count('</body>') != 1:
        raise ValueError('Unexpected baseline structure')
    if 'prymage-synthetic-tracking' in baseline or '</script' in script.lower():
        raise ValueError('Existing tracking release or unsafe embedded script')
    policy = '<meta id="prymage-synthetic-tracking" http-equiv="Content-Security-Policy" content="default-src \'none\'; script-src \'unsafe-inline\'; style-src \'unsafe-inline\'; img-src data:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">'
    return baseline.replace('<head>', '<head>' + policy, 1).replace('</body>', '<script>' + script + '</script></body>', 1)


def create(baseline: str, script: str, directory: Path, repository: str, revision: str):
    if repository != REPOSITORY or not revision:
        raise ValueError('Synthetic tracking release requires the isolated sandbox and a base commit')
    text = candidate(baseline, script)
    proposal = WebsiteProposal(str(uuid.uuid4()), 'synthetic_tracking', digest(script),
        'Network-isolated headline tracking preview; synthetic data only',
        ('docs/sandbox-experiment-tracking.md',), repository, 'pages-test', digest(baseline), revision)
    manifest = {'proposal':asdict(proposal), 'content_hash':digest(text)}
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in [('baseline.html',baseline),('candidate.html',text),('preview.html',text)]:
        (directory/name).write_bytes(content.encode('utf-8'))
    (directory/'manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    return manifest


def verify(directory: Path, expected: str, repository: str, environment: str, current: str):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    if manifest['proposal']['field'] == 'synthetic_ga4_tracking':
        from .ga4_bundle import verify as verify_ga4
        return verify_ga4(directory, expected, repository, environment, current)
    proposal = WebsiteProposal(**manifest['proposal'])
    script = Path('experiment-preview.js').read_text(encoding='utf-8')
    baseline = (directory/'baseline.html').read_bytes().decode('utf-8')
    text = (directory/'candidate.html').read_bytes().decode('utf-8')
    if repository != REPOSITORY or (proposal.repository,proposal.environment) != (repository,environment) or environment != 'pages-test':
        raise ValueError('Tracking target mismatch')
    if proposal.field != 'synthetic_tracking' or proposal.proposed_text != digest(script):
        raise ValueError('Tracking module changed')
    if current != baseline or digest(current) != proposal.base_hash:
        raise ValueError('Tracking baseline changed')
    if text != candidate(baseline,script) or expected != digest(text) or manifest['content_hash'] != expected:
        raise ValueError('Tracking candidate changed')
    if not proposal.base_revision or not proposal.rationale or not proposal.evidence_ids:
        raise ValueError('Tracking provenance is incomplete')
    return manifest


def approve(directory: Path, manifest: dict):
    created = datetime.fromisoformat(os.environ['STAGING_RUN_CREATED_AT'].replace('Z','+00:00'))
    expiry = created + timedelta(hours=24)
    now = datetime.now(timezone.utc)
    if not created <= now < expiry:
        raise ValueError('Tracking preview expired or future-dated')
    proposal = manifest['proposal']
    receipt = {'proposal_id':proposal['proposal_id'],'content_hash':manifest['content_hash'],
        'base_hash':proposal['base_hash'],'repository':proposal['repository'],'environment':'pages-test',
        'approver':os.environ['GITHUB_ACTOR'],'approved_at':now.isoformat(),
        'expires_at':expiry.isoformat(),'execution_state':'APPROVED'}
    (directory/'approval.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')


if __name__ == '__main__':
    mode = os.environ.get('STAGING_TRACKING_MODE', 'local')
    script_name = 'experiment-preview.js'
    if mode == 'ga4':
        from .ga4_bundle import create
        script_name = 'experiment-ga4.js'
    elif mode != 'local':
        raise ValueError('Unsupported tracking mode')
    manifest = create(Path('index.html').read_bytes().decode('utf-8'),
        Path(script_name).read_text(encoding='utf-8'), Path('candidate-bundle'),
        os.environ['GITHUB_REPOSITORY'],os.environ['GITHUB_SHA'])
    print(json.dumps(manifest,indent=2))
