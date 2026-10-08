"""Trusted workflow release ledger and compare-and-swap Git publication.

Only deploy workflow-owned bundles after provenance and actor checks. Source
and receipts are committed before Pages deployment, consuming the old base.
"""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from .bundle import verify_bundle
from .html_updater import digest


def git(*args: str) -> str:
    result = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
    return result.stdout.strip()


def commit_release(site: Path, ledger: Path, record: dict, expected_revision: str) -> str:
    """A normal push rejects any intervening remote commit (never force push)."""
    if git("rev-parse", "HEAD") != expected_revision:
        raise ValueError("Checkout base changed")
    remote = git("ls-remote", "origin", "refs/heads/main").split()[0]
    if remote != expected_revision:
        raise ValueError("Remote main changed")
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps(record, indent=2), encoding="utf-8")
    git("add", "--", str(site), str(ledger))
    git("-c", "user.name=Prymage Staging", "-c",
        "user.email=staging@users.noreply.github.com", "commit", "-m",
        "Record approved sandbox deployment")
    git("push", "origin", "HEAD:refs/heads/main")
    return git("rev-parse", "HEAD")


def run(command: str, bundle: Path, site: Path):
    context_path = bundle / "execution.json"
    if command in ("prepare", "preflight"):
        if os.environ["GITHUB_RUN_ATTEMPT"] != "1":
            raise ValueError("Reruns cannot replay approval; stage a new proposal")
        if os.environ["GITHUB_REF"] != "refs/heads/main":
            raise ValueError("Publication must run from main")
        metadata = json.loads((bundle / "run.json").read_text(encoding="utf-8"))
        revision = git("rev-parse", "HEAD")
        if (metadata["path"] != ".github/workflows/stage.yml" or
                metadata["event"] != "workflow_dispatch" or
                metadata["conclusion"] != "success" or
                metadata["head_sha"] != revision or
                metadata["repository"]["full_name"] != os.environ["GITHUB_REPOSITORY"]):
            raise ValueError("Untrusted/stale preview run")
        os.environ["STAGING_BASE_REVISION"] = revision
        os.environ["STAGING_RUN_CREATED_AT"] = metadata["created_at"]
        os.environ["STAGING_AUTHENTICATED_ACTOR"] = os.environ["GITHUB_ACTOR"]
        actor = os.environ["GITHUB_ACTOR"].casefold()
        allowed = {item.strip().casefold() for item in os.environ["STAGING_APPROVERS"].split(",")}
        if actor not in allowed:
            raise SystemExit("Unauthorized workflow actor")
        manifest = verify_bundle(bundle, os.environ["STAGING_EXPECTED_HASH"],
                                 os.environ["GITHUB_REPOSITORY"], "pages-test",
                                 site.read_bytes().decode("utf-8"))
        drill = os.environ.get("STAGING_ROLLBACK_DRILL", "false") == "true"
        if drill and (os.environ["GITHUB_REPOSITORY"] != "lee-jr11/prymage-staging-sandbox" or
                      manifest["content_hash"] != manifest["proposal"]["base_hash"]):
            raise ValueError("Rollback drill is restricted to unchanged HTML in the sandbox")
        if command == "preflight":
            return
        from .__main__ import main
        previous = sys.argv
        try:
            sys.argv = ["staging", "approve-bundle", "--site", str(site),
                        "--bundle", str(bundle)]
            main()
        finally:
            sys.argv = previous
        manifest = verify_bundle(bundle, os.environ["STAGING_EXPECTED_HASH"],
                                 os.environ["GITHUB_REPOSITORY"], "pages-test",
                                 site.read_bytes().decode("utf-8"))
        proposal_id = manifest["proposal"]["proposal_id"]
        ledger = Path("deployment-records") / (proposal_id + ".json")
        if ledger.exists():
            raise ValueError("Proposal already executed")
        record = {"proposal_id": proposal_id, "content_hash": manifest["content_hash"],
                  "base_hash": manifest["proposal"]["base_hash"],
                  "base_revision": revision, "status": "PUBLISHING",
                  "approval": json.loads((bundle / "approval.json").read_text()),
                  "workflow_run_id": os.environ["GITHUB_RUN_ID"],
                  "rollback_drill": drill,
                  "updated_at": datetime.now(timezone.utc).isoformat()}
        record["approval"]["execution_state"] = "CONSUMED"
        site.write_bytes((bundle / "candidate.html").read_bytes())
        execution_revision = commit_release(site, ledger, record, revision)
        context_path.write_text(json.dumps({"ledger": str(ledger),
                                           "revision": execution_revision}), encoding="utf-8")
        return
    context = json.loads(context_path.read_text(encoding="utf-8"))
    ledger = Path(context["ledger"])
    record = json.loads(ledger.read_text(encoding="utf-8"))
    revision = context["revision"]
    if command == "rollback":
        if record["status"] != "PUBLISHING" or digest(site.read_bytes().decode(
                "utf-8")) != record["content_hash"]:
            raise ValueError("Current release differs; rollback refused")
        site.write_bytes((bundle / "baseline.html").read_bytes())
        record["status"] = "ROLLING_BACK"
    elif command == "verified":
        if record["status"] != "PUBLISHING":
            raise ValueError("Unexpected release state")
        record["status"] = "VERIFIED"
    elif command in ("rolled-back", "rollback-failed"):
        if record["status"] != "ROLLING_BACK":
            raise ValueError("Unexpected rollback state")
        record["status"] = "ROLLED_BACK" if command == "rolled-back" else "ROLLBACK_FAILED"
    else:
        raise ValueError("Unknown release operation")
    record["updated_at"] = datetime.now(timezone.utc).isoformat()
    next_revision = commit_release(site, ledger, record, revision)
    context["revision"] = next_revision
    context_path.write_text(json.dumps(context), encoding="utf-8")


if __name__ == "__main__":
    try:
        run(sys.argv[1], Path("candidate-bundle"), Path("index.html"))
    except Exception as exc:
        directory = Path("candidate-bundle")
        if directory.exists():
            (directory / "incident.json").write_text(json.dumps({
                "operation": sys.argv[1], "status": "MANUAL_RECOVERY_REQUIRED",
                "error_type": type(exc).__name__,
                "instruction": "Inspect source ledger and Pages deployment before retrying."},
                indent=2), encoding="utf-8")
        raise
