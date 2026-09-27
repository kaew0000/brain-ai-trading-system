# MIGRATION — AI Self-Improvement Governance Phase 3 / G5: Recommendation Proposals (V16 §72)

## Do you need to do anything?

**Only if `RECOMMENDATION_APPLICATION_ENABLED=True` in your live
`.env`.** If it's unset or `False` (the default — and it's not in
`.env.example`, so most deployments won't have it set), this phase
has zero runtime effect: `run_learning_recommendation_refresh()` still
short-circuits before touching anything, exactly as before.

**If `RECOMMENDATION_APPLICATION_ENABLED=True`:**

- The new `RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL` setting defaults
  to `True`. This means: starting from this phase's first run, freshly
  generated recommendations will **no longer automatically become
  eligible** to nudge live decisions — each one now needs a human to
  approve its proposal via `POST /api/governance/proposals/approve`
  first (list pending ones via `GET /api/governance/proposals?status=pending&proposal_type=recommendation_param`).
  If nothing is ever approved, `RECOMMENDATION_APPLICATION_ENABLED`'s
  live nudging effectively goes quiet (empty eligible list every
  cycle) rather than erroring — a safe, silent fail-closed, but worth
  knowing if you were relying on it actively nudging decisions already.
- To **keep the exact old behavior** (every recommendation immediately
  eligible, no approval step) set
  `RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL=false` in `.env`.
- No dashboard/frontend UI exists yet to approve these visually (same
  gap §58 already noted for `model_promotion` proposals) — approval is
  via the API only, same as `model_promotion` has been since §58. A
  dedicated Track B phase would close this for both types at once.
- A recommendation's approval is valid only until that specific
  recommendation instance's own `expires_at` (governed by
  `RECOMMENDATION_TTL_HOURS`, default 24h) — a still-recurring pattern
  will need re-approval on roughly the same cadence
  `run_learning_recommendation_refresh()` runs (daily). If this creates
  more review overhead than wanted, raising `RECOMMENDATION_TTL_HOURS`
  widens the reuse window; this is a deliberate default, not a bug.

No database migration — `recommendation_param` was already a valid
`proposal_type` in `database/schema_v13.sql`'s CHECK constraint since
§48. No API contract change for any existing endpoint or field. No
rollback considerations beyond a normal `git revert`, or setting
`RECOMMENDATION_PROPOSALS_REQUIRE_APPROVAL=false` to restore the old
behavior without reverting anything.

## Not covered by this phase

`DYNAMIC_AGENT_WEIGHTS_ENABLED` (`agent_weight` governance) —
deliberately deferred to G6 Tier 1. See `docs/architecture.md` §72's
"Scope decision" section for the full reasoning. No action needed:
this flag's behavior is completely unchanged by this phase.
