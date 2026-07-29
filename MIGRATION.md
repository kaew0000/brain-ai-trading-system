# MIGRATION — V16 Phase 4B Step 3D: Unified Trade Lifecycle & Trade Attribution

## Do you need to do anything?

**No code changes required for existing callers.** Every new parameter
(`lifecycle` on `ExecutionOrchestrator`/`ExecutionCoordinator`/
`TradeManager`, `record_attribution` on `notify_position_closed()`,
`reason`/`source`/`symbol`/`duration_seconds`/`confidence` on
`record_trade_outcome()`) has a default that reproduces this
codebase's exact pre-Step-3D behavior. Nothing existing was rewired to
require the new lifecycle layer — it's additive orchestration sitting
in front of the same underlying writes.

## If you want to use the new dashboard endpoint

Already live once this branch is deployed:

```bash
curl http://localhost:8000/api/lifecycle/state
# {"ok": true, "data": {"positions": [], "count": 0}}
```

Empty is expected on a freshly-started process — `TradeLifecycle`'s
`snapshot()` only shows live (non-terminal) handles, and nothing has
opened yet. It fills in automatically as trades open and close through
the now-unified paths, with no further deploy needed.

## Database

No schema change. The 5 new attribution fields
(`reason`/`source`/`symbol`/`duration_seconds`/`confidence`) are stored
as additional keys in the same JSON blob `save_execution_attribution()`
already wrote into `trades.extra_data` — nothing to migrate, no new
table, no new column.

## Configuration

No new settings, no `.env` change required.

## If you're extending this in a future phase

- `TradeLifecycle`'s `CloseSource` enum already has entries for
  `MANUAL_CLOSE`, `LIQUIDATION`, `RISK_CLOSE`, and `CEO_BLOCKED` — none
  of these currently have an automatic trigger anywhere in this
  codebase (see `docs/architecture.md` §32's Part B table). Building
  one of those triggers is additive: call
  `lifecycle.request_exit(symbol, CloseSource.X, reason)` from wherever
  the new detection logic lives — the lifecycle, journal, and portfolio
  wiring is already there waiting for a caller.
- `execution/execution_factory.py::build_execution_engine()` is the one
  documented gap left by this phase — it doesn't thread the shared
  `get_default_trade_lifecycle()` singleton through to the
  `TradeManager`/`ExecutionCoordinator` instances it builds for the
  real paper/testnet/live bootstrap path. Threading it through is a
  small, additive change to that one factory function.

## What is explicitly NOT part of this migration

- No CEOAgent/PortfolioSignalProvider/MarketScanner/OpportunityRanker/
  RegimeEngine changes — untouched, per this phase's own constraints.
- No natural SL/TP close detection for the multi-symbol path — still
  doesn't exist.
- No dashboard UI page consuming `/api/lifecycle/*` yet — the read API
  exists, nothing renders it.

## Rollback

Every change in this phase is additive at the interface level. A full
revert of the single commit on
`feature/phase4b-step3d-unified-trade-lifecycle` removes:

- New files: `execution/trade_lifecycle.py`, `api/lifecycle_api.py`,
  and 4 new test files.
- Reverts small, additive edits to: `journal/trade_attribution.py`,
  `portfolio/portfolio_manager.py`, `execution/execution_orchestrator.py`,
  `execution/execution_coordinator.py`, `execution/trade_manager.py`,
  `main.py`, `system_health/recovery_engine.py`, `api/app.py`.
- Reverts 3 updated assertions in `tests/test_execution_orchestrator.py`
  back to checking `notify_position_closed()`'s kwargs directly (valid
  again once the lifecycle-routing revert above is also applied).

No database rollback needed — no schema change this phase, and the new
attribution fields being absent from older rows is already handled
gracefully (every `record_trade_outcome()` field is optional and
`None` by default, same as before this phase).
