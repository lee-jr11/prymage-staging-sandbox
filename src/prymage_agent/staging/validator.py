"""Reject malformed proposals; protect the complete non-editable baseline."""
import re
import unicodedata
from html import unescape

from .html_updater import FIELDS, apply_text, digest, protected_source, spans
from .schemas import ProposalValidationResult, WebsiteProposal

LIMITS = {"page_title": 70, "meta_description": 160, "hero_headline": 100,
          "hero_subhead": 300, "hero_cta_text": 40}


def validate(baseline: str, proposal: WebsiteProposal,
             candidate: str | None = None) -> ProposalValidationResult:
    errors = []
    for name in ("proposal_id", "field", "proposed_text", "rationale", "repository",
                 "environment", "base_hash", "base_revision"):
        if not isinstance(getattr(proposal, name), str):
            errors.append(f"{name} must be text")
    if not isinstance(baseline, str) or len(baseline.encode("utf-8")) > 1_000_000:
        errors.append("Baseline must be UTF-8 HTML of at most 1 MB")
    if errors:
        return ProposalValidationResult(False, tuple(errors), tuple(FIELDS))
    text = proposal.proposed_text
    if proposal.field not in FIELDS:
        errors.append("Unknown editable field")
    if not isinstance(text, str) or not text.strip():
        errors.append("Text must be nonempty")
    elif proposal.field in LIMITS:
        if len(text) > LIMITS[proposal.field]:
            errors.append(f"Text exceeds {LIMITS[proposal.field]} characters")
        if any(unicodedata.category(char).startswith("C") for char in text):
            errors.append("Control, formatting or invalid Unicode characters")
        decoded = text
        for _ in range(3):
            decoded = unescape(decoded)
        if any(char in decoded for char in "<>") or re.search(
                r"(?i)(javascript\s*:|data\s*:|on\w+\s*=)", decoded):
            errors.append("Markup or executable text is not allowed")
    if "\ufffd" in text:
        errors.append("Replacement characters indicate broken text encoding")
    if (not isinstance(proposal.rationale, str) or not proposal.rationale.strip() or
            not isinstance(proposal.evidence_ids, (tuple, list)) or
            not proposal.evidence_ids or any(not isinstance(item, str) or not item.strip()
                                            for item in proposal.evidence_ids)):
        errors.append("Rationale and evidence IDs are required")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", proposal.proposal_id):
        errors.append("Invalid proposal ID")
    if not proposal.repository or not proposal.environment:
        errors.append("Repository and environment are required")
    if digest(baseline) != proposal.base_hash:
        errors.append("Stale base hash")
    if not errors:
        try:
            spans(baseline)
            if "G-XXXXXXXXXX" in baseline:
                errors.append("Configure real pilot tracking before freezing the baseline")
            for required in ("handleDemoClick", "handleLeadSubmit"):
                if not re.search(r"function\s+" + required + r"\s*\(", baseline):
                    errors.append(f"Baseline handler missing: {required}")
            for required in ("lead-form", "contact-name", "contact-email", "contact-region",
                             "contact-interest", "btn-submit-lead"):
                if len(re.findall(r'\bid=[\"\']' + required + r'[\"\']', baseline)) != 1:
                    errors.append(f"Baseline requires exactly one {required}")
            expected = apply_text(baseline, proposal.field, text)
            if candidate is not None:
                if candidate != expected:
                    errors.append("Candidate differs from the approved surgical update")
                if protected_source(baseline, proposal.field) != protected_source(
                        candidate, proposal.field):
                    errors.append("Protected content changed")
        except (ValueError, TypeError) as exc:
            errors.append(str(exc))
    return ProposalValidationResult(not errors, tuple(errors), tuple(FIELDS))
