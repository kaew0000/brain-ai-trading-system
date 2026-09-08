# MIGRATION — Nightly Retrain Governance Gate, Phase 2 (V16 §58)

## Do you need to do anything?

**Behavior changes automatically on restart — read this before your
next nightly retrain runs.** As of this merge, a model that beats
`should_promote()`'s gate will **no longer go active on its own**. It
gets registered (saved, inactive) and a pending proposal is created
instead. If you take no action, that model simply never goes live —
the previous model stays active indefinitely. This is the intended
behavior (that's the whole point of the gate), but it means **you now
need to check `GET /api/governance/proposals?status=pending`
periodically** (e.g. the morning after a nightly retrain) or nothing
new will ever get promoted.

## How to approve or reject a pending proposal today

No dashboard button yet (see PATCH_NOTES.md's "Known follow-up") — use
the API directly:

```bash
# List what's pending
curl -H "Authorization: Bearer $YOUR_API_KEY" \
  "http://<host>:<port>/api/governance/proposals?status=pending"

# Approve #7 -- this immediately promotes the model too (one step)
curl -X POST -H "Authorization: Bearer $YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"proposal_id": 7}' \
  "http://<host>:<port>/api/governance/proposals/approve"

# Or reject it
curl -X POST -H "Authorization: Bearer $YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"proposal_id": 7, "reason": "sample size too small"}' \
  "http://<host>:<port>/api/governance/proposals/reject"
```

Both `approve` and `reject` require `OPERATOR`-tier auth (same as
arming a risk override) — a `VIEWER`-scoped key will get a 403.

## If you want the old unattended behavior back

Set `MODEL_PROMOTION_REQUIRES_APPROVAL=False` in your environment and
restart. `run_nightly_retrain()` goes back to promoting a model the
moment it beats `should_promote()`, with no proposal, no review, no
human step — identical to pre-§58 behavior. Not recommended for the
live account; reasonable for a dev/testnet environment where
unattended promotion is actually wanted.

## Rollback

Revert this branch and restart. `run_nightly_retrain()` goes back to
calling `ModelRegistry.promote()` directly and unconditionally; the
three new `/api/governance/proposals*` endpoints disappear (any
pending proposals created while this branch was live stay harmlessly
in the `update_proposals` table, just no longer reachable via the API
until this branch is reapplied).
