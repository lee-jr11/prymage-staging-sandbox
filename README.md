# Prymage staging sandbox

Static copy-change test site, not the company website.

Set repository variable STAGING_APPROVERS to comma-separated authorized GitHub usernames. Enable Pages with GitHub Actions as its source. Run Stage website copy, review the downloadable preview and exact candidate hash, then dispatch Approve and publish sandbox copy with that run ID and hash. Approvals expire after 24 hours; reruns and stale bases are rejected. Deployment records are committed before publication.

Preview/browser checks block external tracking. Published pages use the pilot GA4 stream. All test page submissions are simulated, not real leads.

Restrict repository write access and require reviewed changes to scripts/workflows. All Pages deployments must use the serialized publish workflow. Never force push or bypass an interrupted deployment ledger; inspect Pages and source first.
