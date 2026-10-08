"""Immutable staging contracts. These records contain no credentials."""
from dataclasses import dataclass


@dataclass(frozen=True)
class WebsiteProposal:
    proposal_id: str
    field: str
    proposed_text: str
    rationale: str
    evidence_ids: tuple[str, ...]
    repository: str
    environment: str
    base_hash: str
    base_revision: str = ""


@dataclass(frozen=True)
class ProposalValidationResult:
    is_valid: bool
    errors: tuple[str, ...]
    checked_fields: tuple[str, ...]


@dataclass(frozen=True)
class ApprovalReceipt:
    proposal_id: str
    content_hash: str
    base_hash: str
    repository: str
    environment: str
    approver: str
    approved_at: str
    expires_at: str
    execution_state: str = "APPROVED"


@dataclass(frozen=True)
class DeploymentRecord:
    proposal_id: str
    content_hash: str
    status: str
    rollback_reference: str
    detail: str = ""
