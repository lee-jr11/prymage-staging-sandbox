"""Portable CLI, also used by the isolated site's workflow templates."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import uuid

from .bundle import create_bundle, verify_bundle
from .html_updater import digest
from .lifecycle import Lifecycle, http_health
from .schemas import WebsiteProposal


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("stage", "verify", "health", "approve-bundle"))
    parser.add_argument("--site", default="index.html")
    parser.add_argument("--bundle", default="candidate-bundle")
    parser.add_argument("--url")
    args = parser.parse_args()
    directory = Path(args.bundle)
    if args.command == "health":
        if not args.url or not http_health(args.url, Path(args.site).read_bytes().decode(
                "utf-8"), attempts=8, delay=5):
            raise SystemExit("Health verification failed")
        return
    repository = os.environ["STAGING_REPOSITORY"]
    environment = os.environ.get("STAGING_ENVIRONMENT", "pages-test")
    source = Path(args.site).read_bytes().decode("utf-8")
    if args.command == "stage":
        proposal = WebsiteProposal(str(uuid.uuid4()), os.environ["STAGING_FIELD"],
                                   os.environ["STAGING_TEXT"], os.environ["STAGING_RATIONALE"],
                                   tuple(json.loads(os.environ["STAGING_EVIDENCE_IDS"])),
                                   repository, environment, digest(source),
                                   os.environ.get("STAGING_BASE_REVISION", ""))
        manifest = create_bundle(source, proposal, directory)
        print(json.dumps(manifest, indent=2))
        return
    manifest = verify_bundle(directory, os.environ["STAGING_EXPECTED_HASH"],
                             repository, environment, source)
    revision = manifest["proposal"]["base_revision"]
    if not revision or revision != os.environ["STAGING_BASE_REVISION"]:
        raise SystemExit("Base commit changed")
    if args.command == "approve-bundle":
        # Must be called by a workflow authenticating the GitHub actor and
        # verifying artifact provenance first. Environment names are not auth.
        actor = os.environ["STAGING_AUTHENTICATED_ACTOR"]
        allowed = {item.strip().casefold() for item in os.environ[
            "STAGING_APPROVERS"].split(",") if item.strip()}
        if actor.casefold() not in allowed:
            raise SystemExit("Authenticated actor is not an approver")
        created = datetime.fromisoformat(os.environ["STAGING_RUN_CREATED_AT"].replace(
            "Z", "+00:00"))
        expiry = created + timedelta(hours=24)
        remaining = expiry - datetime.now(timezone.utc)
        if remaining <= timedelta(0) or remaining > timedelta(hours=24):
            raise SystemExit("Bundle expired or has an invalid creation date")
        proposal = WebsiteProposal(**manifest["proposal"])
        lifecycle = Lifecycle(directory / "execution.sqlite3", repository, environment,
                              {actor})
        try:
            lifecycle.stage(source, proposal)
            receipt = lifecycle.approve(proposal.proposal_id, manifest["content_hash"],
                                        actor, expires_in=remaining)
            from dataclasses import asdict
            (directory / "approval.json").write_text(json.dumps(asdict(receipt), indent=2),
                                                      encoding="utf-8")
        finally:
            lifecycle.close()
    print("Exact candidate, base and target verified")


if __name__ == "__main__":
    main()
