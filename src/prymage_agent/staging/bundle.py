"""Portable candidate bundles for authenticated GitHub workflow approval."""
from dataclasses import asdict
import json
from pathlib import Path

from .html_updater import apply_text, digest
from .schemas import WebsiteProposal
from .validator import validate


def create_bundle(baseline: str, proposal: WebsiteProposal, output: Path):
    result = validate(baseline, proposal)
    if not result.is_valid:
        raise ValueError("; ".join(result.errors))
    candidate = apply_text(baseline, proposal.field, proposal.proposed_text)
    output.mkdir(parents=True, exist_ok=False)
    (output / "baseline.html").write_bytes(baseline.encode("utf-8"))
    (output / "candidate.html").write_bytes(candidate.encode("utf-8"))
    manifest = {"proposal": asdict(proposal), "content_hash": digest(candidate)}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    # Preview only: stop external scripts and network calls, keeping the exact
    # candidate separately downloadable for approval. No GA4 pollution.
    policy = '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
    policy += "script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'; "
    policy += "img-src data:; form-action 'none'; base-uri 'none'\">"
    preview = candidate.replace("<head>", "<head>" + policy, 1)
    if preview == candidate:
        raise ValueError("Preview requires a literal head element")
    (output / "preview.html").write_bytes(preview.encode("utf-8"))
    return manifest


def verify_bundle(directory: Path, expected_hash: str, repository: str,
                  environment: str, current: str) -> dict:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    proposal = WebsiteProposal(**manifest["proposal"])
    baseline = (directory / "baseline.html").read_bytes().decode("utf-8")
    candidate = (directory / "candidate.html").read_bytes().decode("utf-8")
    if (proposal.repository, proposal.environment) != (repository, environment):
        raise ValueError("Bundle target mismatch")
    if expected_hash != digest(candidate) or manifest["content_hash"] != expected_hash:
        raise ValueError("Candidate hash mismatch")
    if digest(current) != proposal.base_hash:
        raise ValueError("Current base changed")
    result = validate(baseline, proposal, candidate)
    if not result.is_valid:
        raise ValueError("; ".join(result.errors))
    return manifest
