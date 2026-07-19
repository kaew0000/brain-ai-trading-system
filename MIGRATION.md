# MIGRATION — V16 Phase 2C: Portfolio API

## Do you need to do anything?

**No code changes required for existing callers.** Nothing in Phase 2A
or Phase 2B (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, `portfolio_history.save_decision()`/
`get_latest_decisions()`, every existing dataclass) changed signature,
behavior, or default. This phase only adds new files plus new,
additive functions — nothing existing was touched in a way that affects
any current caller.

## If you want to start using the API

It's already live once this branch is deployed — `api/app.py` includes
both routers unconditionally, no feature flag or config change needed.

```bash
curl http://localhost:8000/api/portfolio/state
# {"ok": true, "data": {"positions": [], "total_capital_allocated": 0.0,
#   "blocked": null, "source": "latest_persisted_decision", "live": false,
#   "as_of": null, "note": "No portfolio decision has ever been persisted yet..."}}
```

That empty response is **expected and correct** today — see PATCH_NOTES.md's
"No decision ever persisted" section. It will start reflecting real data
automatically, with no further deploy, the moment some future phase
starts calling `PortfolioManager.decide()` + `portfolio_history.save_decision()`
on a schedule.

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/portfolio");
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // msg.type: "init" | "heartbeat" | "decision" | "state" | "sectors"
  //         | "allocations" | "replacement_proposal"
};
```

## Database

No schema change. `portfolio_history` already exists (Phase 2B). This
phase only adds two new *read* functions
(`portfolio_history.query_decisions()`, `count_decisions()`) — no new
table, no new column, no migration step, nothing to apply.

## Configuration

No new settings. No `.env` change required to deploy.

## Auth

No change to `api/auth.py`. `/api/portfolio/*` already falls under
`_auth_middleware`'s existing default (any `/api/*` path not explicitly
public requires at least VIEWER role, exactly like every other `/api/*`
route already added in P1-A). `/ws/portfolio` calls the existing
`enforce_ws_role(ws, Role.VIEWER)`, same as `/ws/decision`/`/ws/agents`/
`/ws/missions`. If `API_AUTH_ENABLED=false` (the current default per
the startup warning), these routes are open like everything else already
is — this phase doesn't change that posture either way.

## What is explicitly NOT part of this migration

- No scheduler/orchestrator wiring — `portfolio_history` stays empty in
  production until that separate future phase exists.
- No execution wiring, no order placement, no Binance calls anywhere in
  this phase's new code.
- No dashboard page. Nothing in `dashboard_src/`/`dashboard/` was
  touched.
- No changes to `RiskEngine`, `CapitalManager`, `PortfolioManager`,
  `SectorEngine`, or any Phase 2A/2B dataclass.

## Rollback (code)

This entire phase lives in three new files
(`api/portfolio_api.py`, `api/portfolio_ws.py`,
`api/portfolio_serializers.py`) plus additive-only edits to two existing
ones (`portfolio/portfolio_history.py`: two new functions appended;
`api/app.py`: three import lines, two `include_router()` calls, one
`await` inside the existing broadcast loop, one docstring update).
Reverting the single commit on `feature/phase2c-portfolio-api` — or
simply not merging the branch — fully removes it with zero impact on
Phase 2A/2B functionality, since nothing they already shipped was
modified. No database rollback needed (no schema change this phase).
