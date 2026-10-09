"""Exact opt-in GA4 upgrade of the previously reviewed synthetic module."""
from dataclasses import asdict
import json
from pathlib import Path
import uuid

from .html_updater import digest
from .schemas import WebsiteProposal
from .tracking_bundle import REPOSITORY, candidate as isolated_candidate


def candidate(baseline: str, script: str) -> str:
    old_script = Path('experiment-preview.js').read_text(encoding='utf-8')
    old_policy = isolated_candidate('<head></body>', old_script).split('<head>',1)[1].split('<script>',1)[0]
    ending = '<script>' + old_script + '</script></body>'
    if baseline.count(old_policy) != 1 or baseline.count(ending) != 1:
        raise ValueError('Expected exact reviewed synthetic baseline')
    plain = baseline.replace(old_policy, '', 1).replace(ending, '</body>', 1)
    if isolated_candidate(plain, old_script) != baseline:
        raise ValueError('Prior synthetic module changed')
    original_loader = '<script async src="https://www.googletagmanager.com/gtag/js?id=G-EP0Y94K2B6"></script>'
    original_config = "'debug_mode': true // Enables GA4 DebugView for real-time verification"
    if plain.count(original_loader) != 1 or plain.count(original_config) != 1:
        raise ValueError('Pilot GA4 baseline changed')
    plain = plain.replace(original_loader, '<!-- Pilot GA4 loader is gated by telemetry=ga4-test. -->', 1)
    plain = plain.replace("    gtag('js', new Date());", "    window['ga-disable-G-EP0Y94K2B6'] = true;\n    gtag('js', new Date());", 1)
    plain = plain.replace(original_config, "'debug_mode': true, 'send_page_view': false, 'allow_google_signals': false, 'allow_ad_personalization_signals': false", 1)
    result = isolated_candidate(plain, script)
    return result.replace("script-src 'unsafe-inline';", "script-src 'unsafe-inline' https://www.googletagmanager.com;", 1).replace("connect-src 'none';", "connect-src https://www.google-analytics.com https://region1.google-analytics.com;", 1)


def create(baseline, script, directory, repository, revision):
    if repository != REPOSITORY or not revision:
        raise ValueError('Pilot GA4 upgrade requires sandbox and base commit')
    text = candidate(baseline, script)
    proposal = WebsiteProposal(str(uuid.uuid4()), 'synthetic_ga4_tracking', digest(script),
        'Opt-in pilot GA4 collection; separate synthetic event names',
        ('docs/sandbox-ga4-tracking.md',), repository, 'pages-test', digest(baseline), revision)
    manifest = {'proposal': asdict(proposal), 'content_hash': digest(text)}
    directory.mkdir(parents=True, exist_ok=False)
    for name, content in [('baseline.html', baseline), ('candidate.html', text), ('preview.html', text)]:
        (directory/name).write_bytes(content.encode('utf-8'))
    (directory/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def verify(directory, expected, repository, environment, current):
    manifest = json.loads((directory/'manifest.json').read_text(encoding='utf-8'))
    proposal = WebsiteProposal(**manifest['proposal'])
    script = Path('experiment-ga4.js').read_text(encoding='utf-8')
    baseline = (directory/'baseline.html').read_bytes().decode('utf-8')
    text = (directory/'candidate.html').read_bytes().decode('utf-8')
    if repository != REPOSITORY or (proposal.repository, proposal.environment) != (repository, environment) or environment != 'pages-test':
        raise ValueError('Pilot GA4 target mismatch')
    if proposal.field != 'synthetic_ga4_tracking' or proposal.proposed_text != digest(script):
        raise ValueError('Pilot GA4 module changed')
    if current != baseline or digest(current) != proposal.base_hash:
        raise ValueError('Pilot GA4 baseline changed')
    if text != candidate(baseline, script) or expected != digest(text) or manifest['content_hash'] != expected:
        raise ValueError('Pilot GA4 candidate changed')
    if not proposal.base_revision or not proposal.rationale or not proposal.evidence_ids:
        raise ValueError('Pilot GA4 provenance incomplete')
    return manifest
