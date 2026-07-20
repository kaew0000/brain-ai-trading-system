# MIGRATION — V16 Phase 2C + feat(world-performance-v1) + Phase 2E: Execution Wiring & Live Orchestrator

## Backend: Phase 2C — Portfolio API

### Do you need to do anything?

**No code changes required for existing callers.** Nothing in Phase 2A
or Phase 2B (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, `portfolio_history.save_decision()`/
`get_latest_decisions()`, every existing dataclass) changed signature,
behavior, or default. This phase only adds new files plus new,
additive functions — nothing existing was touched in a way that affects
any current caller.

### If you want to start using the API

It's already live once this branch is deployed — `api/app.py` includes
both routers unconditionally, no feature flag or config change needed.

```bash
curl http://localhost:8000/api/portfolio/state
# {"ok": true, "data": {"positions": [], "total_capital_allocated": 0.0,
#   "blocked": null, "source": "latest_persisted_decision", "live": false,
#   "as_of": null, "note": "No portfolio decision has ever been persisted yet..."}}
```

## Backend: Phase 2E — Execution Wiring & Live Orchestrator

### Do you need to do anything?

**No code changes required for existing callers.** Nothing in Phase 2A,
2B, or 2C (`CapitalManager`, `PortfolioManager`, `PortfolioState`,
`SectorEngine`, `portfolio_api.py`, `portfolio_ws.py`,
`portfolio_history.py`, every existing dataclass) changed signature,
behavior, or default. `execution/execution_coordinator.py` gained one
new method (`close_position()`) — every existing method on it
(`execute_trade()`, health/shutdown, `__getattr__` passthrough) is
unchanged. This phase only adds new files plus additive changes —
nothing existing was touched in a way that affects any current caller.

### If you want to start using ExecutionOrchestrator

It is **not** wired into any running loop yet — no scheduler calls it
in production (see PATCH_NOTES.md's "explicitly not built" list). To
use it today, a caller constructs one directly:

```python
from execution.execution_factory import build_execution_engine
from execution.execution_orchestrator import ExecutionOrchestrator, ExecutionSignal
from portfolio.portfolio_manager import PortfolioManager  # or your existing instance

engine = build_execution_engine()  # paper/testnet/live per settings, unchanged

def my_signal_provider(symbol: str):
    # Wire up whatever produces entry/stop-loss/take-profit for `symbol`
    # today — this phase defines the interface, not an implementation.
    ...
    return ExecutionSignal(direction=1, entry_price=..., stop_loss=..., take_profit=...)

orchestrator = ExecutionOrchestrator(
    execution_engine=engine,
    portfolio_manager=portfolio_manager,
    signal_provider=my_signal_provider,
)

decision = portfolio_manager.decide(candidates, risk_engine, state, balance)
batch = orchestrator.execute(decision, state, balance)
```

## If you want to start using the new API/WebSocket surface

Already live once this branch is deployed — `api/app.py` includes the
new router unconditionally, no feature flag or config change needed.

```bash
curl http://localhost:8000/api/execution/metrics
# {"ok": true, "data": {"total": 0, "completed": 0, "failed": 0,
#   "cancelled": 0, "pending": 0, "running": 0, "success_rate": 0.0,
#   "failure_rate": 0.0, "retry_rate": 0.0,
#   "average_latency_seconds": 0.0, "per_symbol_counts": {}}}
```

That all-zeros response is **expected and correct** until something
actually constructs an `ExecutionOrchestrator` and calls `execute()` —
see PATCH_NOTES.md's limitations section. It updates automatically,
with no further deploy, the moment that happens.

```javascript
const ws = new WebSocket("ws://localhost:8000/ws/portfolio");  // same connection as Phase 2C
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data);
  // msg.type now also includes: "execution_started" | "execution_completed"
  //   | "execution_failed" | "execution_cancelled" | "execution_metrics_updated"
  // alongside the existing "decision" | "state" | "sectors" | "allocations"
  //   | "replacement_proposal" | "heartbeat" | "init"
};
```

## Configuration

Two new optional settings, both with defaults — no `.env` change
required to deploy:

| Setting | Default | Meaning |
|---|---|---|
| `EXECUTION_MAX_RETRIES` | `2` | Orchestration-level retries for recoverable failures (layered above `trade_manager.py`'s own API-level retries) |
| `EXECUTION_RETRY_DELAY_SECONDS` | `0.0` | Pause between orchestration-level retry attempts |

## Database

No schema change. This phase does not persist anything new —
`ExecutionState` is in-memory only (see PATCH_NOTES.md's limitations
list for why execution-outcome persistence is explicitly future work).

## Auth

No change to `api/auth.py`. `/api/execution/*` already falls under
`_auth_middleware`'s existing default (any `/api/*` path not explicitly
public requires at least VIEWER role) — identical reasoning to
`/api/portfolio/*` in Phase 2C. If `API_AUTH_ENABLED=false` (the
current default per the startup warning), these routes are open like
everything else already is — this phase doesn't change that posture
either way.

## What is explicitly NOT part of this migration

- No scheduler/orchestrator wiring into `main.py`'s live trading loop —
  `ExecutionOrchestrator` exists and is fully tested, but nothing calls
  it in production yet.
- No execution-outcome persistence (fills/slippage) into
  `portfolio_history` or any new table.
- No multi-symbol signal-generation implementation — only the
  `signal_provider` interface `ExecutionOrchestrator` depends on.
- No dashboard panel. Nothing in `dashboard_src/`/`dashboard/` was
  touched.
- No changes to `RiskEngine`, `CapitalManager`, `PortfolioManager`,
  `SectorEngine`, `portfolio_api.py`, `portfolio_ws.py`'s existing
  decision-broadcast behavior, or any Phase 2A/2B/2C dataclass.

## Rollback (code)

This entire phase lives in five new files
(`execution/execution_orchestrator.py`, `execution_state.py`,
`execution_metrics.py`, `execution_events.py`, `api/execution_api.py`)
plus additive-only edits to four existing ones
(`execution/execution_coordinator.py`: one new method appended;
`config/settings.py`: two new fields appended;
`api/portfolio_ws.py`: one new function plus one call site added to the
existing tick, dedup state added alongside the existing dedup state;
`api/app.py`: one import line, one `include_router()` call).
Reverting the single commit on `feature/phase2e-execution-wiring` — or
simply not merging the branch — fully removes it with zero impact on
Phase 2A/2B/2C functionality, since nothing they already shipped was
modified. No database rollback needed (no schema change this phase).
