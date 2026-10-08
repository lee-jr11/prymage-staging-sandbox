"""Durable, single-use approvals. Backends must implement compare-and-swap writes.

The local approval method is for a trusted operator, not an authentication API.
Hosted integrations must authenticate the caller before invoking it.
"""
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
from typing import Protocol
from urllib.request import Request, urlopen
import time

from .html_updater import apply_text, digest
from .schemas import ApprovalReceipt, DeploymentRecord, WebsiteProposal
from .validator import validate


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


class Backend(Protocol):
    def read(self) -> str: ...
    def publish(self, content: str, expected_hash: str) -> str: ...
    def healthy(self, content: str) -> bool: ...


class Lifecycle:
    def __init__(self, database: str | Path, repository: str, environment: str,
                 approvers: set[str]):
        self.repository = repository
        self.environment = environment
        self.approvers = frozenset(approvers)
        self.db = sqlite3.connect(database, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS website_staging (
                id TEXT PRIMARY KEY, repository TEXT NOT NULL,
                environment TEXT NOT NULL, proposal TEXT NOT NULL,
                baseline TEXT NOT NULL, candidate TEXT NOT NULL,
                status TEXT NOT NULL, approval TEXT, deployment TEXT);
            CREATE TABLE IF NOT EXISTS website_execution_locks (
                repository TEXT, environment TEXT, proposal_id TEXT,
                PRIMARY KEY(repository, environment));
        """)

    def close(self):
        self.db.close()

    def record(self, proposal_id: str) -> dict:
        row = self.db.execute("SELECT * FROM website_staging WHERE id=?",
                              (proposal_id,)).fetchone()
        if row is None:
            raise ValueError("Unknown proposal")
        if (row["repository"], row["environment"]) != (
                self.repository, self.environment):
            raise ValueError("Wrong deployment target")
        return dict(row)

    def stage(self, baseline: str, proposal: WebsiteProposal) -> str:
        if (proposal.repository, proposal.environment) != (
                self.repository, self.environment):
            raise ValueError("Wrong proposal target")
        result = validate(baseline, proposal)
        candidate = apply_text(baseline, proposal.field, proposal.proposed_text) if (
            result.is_valid) else ""
        with self.db:
            self.db.execute("INSERT INTO website_staging VALUES(?,?,?,?,?,?,?,?,?)",
                            (proposal.proposal_id, self.repository, self.environment,
                             json.dumps(asdict(proposal)), baseline, candidate,
                             "STAGED" if result.is_valid else "REJECTED", None, None))
        if not result.is_valid:
            raise ValueError("; ".join(result.errors))
        return digest(candidate)

    def approve(self, proposal_id: str, content_hash: str, approver: str,
                *, expires_in: timedelta = timedelta(hours=24),
                now: datetime | None = None) -> ApprovalReceipt:
        if approver not in self.approvers:
            raise PermissionError("Approver is not authorized")
        if expires_in <= timedelta(0) or expires_in > timedelta(hours=24):
            raise ValueError("Approval duration must be positive and at most 24 hours")
        moment = now or now_utc()
        if moment.tzinfo is None:
            raise ValueError("Approval time must be timezone-aware")
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.record(proposal_id)
            if row["status"] != "STAGED" or digest(row["candidate"]) != content_hash:
                raise ValueError("Approval requires the exact staged artifact")
            proposal = WebsiteProposal(**json.loads(row["proposal"]))
            if not validate(row["baseline"], proposal, row["candidate"]).is_valid:
                raise ValueError("Stored candidate failed validation")
            receipt = ApprovalReceipt(proposal_id, content_hash, proposal.base_hash,
                                      self.repository, self.environment, approver,
                                      moment.isoformat(), (moment + expires_in).isoformat())
            self.db.execute("UPDATE website_staging SET status='APPROVED', approval=? "
                            "WHERE id=?", (json.dumps(asdict(receipt)), proposal_id))
            self.db.commit()
            return receipt
        except Exception:
            self.db.rollback()
            raise

    def execute(self, proposal_id: str, backend: Backend, *,
                now: datetime | None = None) -> DeploymentRecord:
        moment = now or now_utc()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            row = self.record(proposal_id)
            if row["status"] != "APPROVED":
                raise ValueError("Approval absent or already consumed")
            approval = ApprovalReceipt(**json.loads(row["approval"]))
            proposal = WebsiteProposal(**json.loads(row["proposal"]))
            if (approval.proposal_id != proposal_id or
                    approval.repository != self.repository or
                    approval.environment != self.environment or
                    approval.approver not in self.approvers or
                    approval.execution_state != "APPROVED" or
                    approval.base_hash != digest(row["baseline"]) or
                    approval.content_hash != digest(row["candidate"])):
                raise ValueError("Approval binding changed")
            if not (datetime.fromisoformat(approval.approved_at) <= moment <
                    datetime.fromisoformat(approval.expires_at)):
                raise ValueError("Approval expired or not yet valid")
            if not validate(row["baseline"], proposal, row["candidate"]).is_valid:
                raise ValueError("Staged artifact changed")
            if digest(backend.read()) != approval.base_hash:
                raise ValueError("Live base changed; restage and reapprove")
            self.db.execute("INSERT INTO website_execution_locks VALUES(?,?,?)",
                            (self.repository, self.environment, proposal_id))
            consumed = asdict(approval)
            consumed["execution_state"] = "CONSUMED"
            self.db.execute("UPDATE website_staging SET status='PUBLISHING', approval=? "
                            "WHERE id=?", (json.dumps(consumed), proposal_id))
            self.db.commit()
        except Exception:
            self.db.rollback()
            raise

        reference = ""
        detail = ""
        try:
            reference = backend.publish(row["candidate"], approval.base_hash)
            if not backend.healthy(row["candidate"]):
                raise RuntimeError("Deployment health check failed")
            status = "VERIFIED"
        except Exception as exc:
            # Never overwrite a newer release. Ambiguous outcomes stay visible.
            detail = type(exc).__name__
            try:
                current = digest(backend.read())
                if current == approval.content_hash:
                    backend.publish(row["baseline"], approval.content_hash)
                    status = "ROLLED_BACK" if backend.healthy(row["baseline"]) else (
                        "ROLLBACK_FAILED")
                elif current == approval.base_hash:
                    status = "DEPLOYMENT_FAILED"
                else:
                    status = "ROLLBACK_FAILED"
                    detail = "Current release changed; automatic rollback refused"
            except Exception as rollback_exc:
                status = "ROLLBACK_FAILED"
                detail = type(rollback_exc).__name__
        deployment = DeploymentRecord(proposal_id, approval.content_hash, status,
                                      approval.base_hash, detail)
        data = asdict(deployment)
        data["backend_reference"] = reference
        with self.db:
            self.db.execute("UPDATE website_staging SET status=?, deployment=? WHERE id=?",
                            (status, json.dumps(data), proposal_id))
            self.db.execute("DELETE FROM website_execution_locks WHERE proposal_id=?",
                            (proposal_id,))
        return deployment


def http_health(url: str, expected: str, *, attempts: int = 3,
                delay: float = 1, timeout: float = 10) -> bool:
    """Bounded retries; compare exact served UTF-8 HTML, not just HTTP 200."""
    for attempt in range(attempts):
        try:
            request = Request(url, headers={"Cache-Control": "no-cache"})
            with urlopen(request, timeout=timeout) as response:
                body = response.read(1_000_001)
                if (response.status == 200 and len(body) <= 1_000_000 and
                        digest(body.decode("utf-8")) == digest(expected)):
                    return True
        except (OSError, UnicodeError):
            pass
        if attempt + 1 < attempts:
            time.sleep(delay)
    return False
