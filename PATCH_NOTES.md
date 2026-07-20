<<<<<<< HEAD
# PATCH NOTES — V16 Phase 2C + feat(world-performance-v1)

## Backend: Phase 2C — Portfolio API
=======
# PATCH NOTES — V16 Phase 2E: Execution Wiring & Live Orchestrator
>>>>>>> origin/feature/phase2e-execution-wiring

Branch: `feature/phase2e-execution-wiring`
Base: `main` @ `fc9afa1` (Phase 2C merged)

### Summary

Connects the completed Portfolio system (Phase 2A-2C) to the existing
execution layer. `docs/architecture.md` §20 ("Next up") named this piece
before it existed — this phase builds the "calling ExecutionCoordinator's
per-symbol TradeManager with an OrchestratedDecision's allocations" and
"acting on (or discarding) a ReplacementProposal" work it described,
using the phase name (§20/portfolio_manager.py's own docstrings both
call it "Phase 2E", not "Phase 2D") the repository itself already uses.

**Two things intentionally NOT built, despite being named in the same
breath by §20** (documented, not silently dropped — see
architecture.md §21 "Scope boundary" for the full reasoning):

- Reading real exchange/journal state into a `PortfolioState` each cycle
  — that's reconciliation (`system_health/reconciliation.py` already
  exists for this). `ExecutionOrchestrator` is handed a `PortfolioState`
  and updates it as executions complete; it doesn't construct one.
- A scheduler calling `PortfolioManager.decide()` then
  `ExecutionOrchestrator.execute()` on a timer — `CLAUDE.md`'s own
  priority list has "Execution Scheduler" as a distinct, later priority;
  building it here would be starting a future phase early.

### New modules

| File | Purpose |
|---|---|
| `execution/execution_orchestrator.py` | `ExecutionOrchestrator.execute()` — the core connection this phase builds |
| `execution/execution_state.py` | In-memory execution lifecycle tracking (PENDING→RUNNING→COMPLETED/FAILED/CANCELLED), idempotency ledger |
| `execution/execution_metrics.py` | Pure computation over `ExecutionState` — success/failure/retry rate, latency, per-symbol counts |
| `execution/execution_events.py` | Execution event vocabulary over the existing `EventBus` — no second pub/sub mechanism |
| `api/execution_api.py` | `GET /api/execution/metrics`, `/status`, `/executions[?status=]`, `/executions/{id}` |

### Changes to existing modules

| File | Change |
|---|---|
| `execution/execution_coordinator.py` | `+close_position()` — routes to the correct per-symbol `TradeManager`; needed because the existing `__getattr__` fallback only delegates to the *default* symbol's manager |
| `config/settings.py` | `+EXECUTION_MAX_RETRIES` (default 2), `+EXECUTION_RETRY_DELAY_SECONDS` (default 0.0) |
| `api/portfolio_ws.py` | `+_relay_execution_events()`, called from the existing `check_and_broadcast()` tick — dedup by `EventBus` seq, same shape as the existing dedup-by-row-id decision relay. **A real placement bug was caught and fixed during testing** (see below) |
| `api/app.py` | + 1 import line, + `app.include_router(_execution_router)`. No existing route/behavior changed |
| `docs/architecture.md` | New §21 (design rationale, scope boundary, the placement bug). §20 "Next up" **byte-for-byte untouched** — verified with `diff`, not just asserted |
| `README.md` | Updated repo layout/test count (also corrected an already-stale count unrelated to this phase, since the file was already being touched) |
| `CHANGELOG.md` | New entry at the top, previous entries unchanged |

<<<<<<< HEAD
**Nothing was removed or had its public signature changed.** Every Phase
2A/2B module (`CapitalManager`, `CorrelationEngine`, `PortfolioState`,
`PortfolioManager`, `SectorEngine`, `portfolio_history`) is untouched.
=======
**Nothing was removed or had its public signature changed.** Every
Phase 2A/2B/2C module (`CapitalManager`, `PortfolioManager`,
`PortfolioState`, `SectorEngine`, `portfolio_api.py`, `portfolio_ws.py`,
every existing dataclass) is byte-for-byte unchanged.

## A real bug caught by testing, not just written around

Building test coverage for "cancel a pending execution" surfaced that
`_execute_allocation`'s original `enqueue()` call unconditionally
overwrote any pre-existing record for that `execution_id` — including
one an external caller had *already cancelled*. Fixed with an
`_already_cancelled()` guard checked before `enqueue()` runs; see
`tests/test_execution_orchestrator.py::TestCancellation::
test_preemptive_cancel_of_predicted_execution_id_is_respected`.

Separately, the first draft of the WebSocket relay nested its call
*inside* the decision-broadcast's own early-returns — meaning it would
only ever run in the one tick a portfolio decision also happened to
change in. Since a decision changes far less often than a batch
executes, this would have meant execution events almost never actually
reached clients in practice. Fixed by making the relay call independent
of the decision-broadcast path; see
`tests/test_portfolio_ws.py::TestExecutionEventRelay::
test_execution_event_relayed_when_decision_row_unchanged`, which fails
against the original placement and passes against the fix.
>>>>>>> origin/feature/phase2e-execution-wiring

### Test results

<<<<<<< HEAD
- 92 new tests added. Full suite: 1188 → **1280 passed, 0 failed**.
- `test_portfolio_serializers.py` 33, `test_portfolio_history_query.py` 14,
  `test_portfolio_api.py` 27, `test_portfolio_ws.py` 18.

---

## Frontend: feat(world-performance-v1)

Branch: `feature/world-performance-v1`
Base: `main` @ `fc9afa1` (Phase 2C merged)

### Summary

Frontend performance and UX pass for Brain Bot V16 Dashboard. Introduces
React.lazy code-splitting, Zustand store equality guards, World HQ Minimap
v2, and a new Portfolio Dashboard backed by MockDataProvider adapters.

### Changes
=======
REST (all under `/api/execution`, existing VIEWER-role auth applies
automatically — no `api/auth.py` change needed):

| Method | Path | Returns |
|---|---|---|
| GET | `/metrics` | Process-wide cumulative `ExecutionMetricsSnapshot` |
| GET | `/status` | Current pending/running/completed/failed/cancelled counts |
| GET | `/executions` | Recent execution records, newest-first; `?status=`, `&limit=` |
| GET | `/executions/{id}` | Single record, or `200 {"data": null}` if not found (not a 404) |

WebSocket: existing `/ws/portfolio` connection now also emits
`execution_started`/`_completed`/`_failed`/`_cancelled`/
`_metrics_updated` frames — no new route, no protocol change to the
existing `decision`/`state`/`sectors`/`allocations`/
`replacement_proposal`/`heartbeat` frames.
>>>>>>> origin/feature/phase2e-execution-wiring

#### Architecture
- **Code Splitting**: All routes converted to `React.lazy()` with `<Suspense>`
  fallback (`PageLoader`). Initial bundle no longer eagerly loads every page.
- **Error Boundary**: Global `ErrorBoundary` in `main.tsx` prevents white-screen
  crashes and offers a branded recovery UI.
- **Store Equality**: All Zustand stores now use shallow / semantic equality
  guards, eliminating re-render storms caused by 1 Hz WS heartbeats with
  unchanged payloads.

<<<<<<< HEAD
#### World HQ
- **WorldPage**: Wrapped in `React.memo`; NPC position updates throttled to
  200 ms; event listeners use named `off()` cleanup instead of
  `removeAllListeners()`.
- **Minimap v2**: Offscreen canvas caches static terrain; room label tooltips on
  hover; CSS `backdrop-blur` overlay; `willReadFrequently` canvas hint.
- **Asset Pipeline**: New `AssetPipeline.ts` utility for priority-based asset
  preloading (critical / deferred / on-demand).

#### Portfolio Dashboard
- **MockDataProvider**: `MockPortfolioProvider` delivers realistic mock portfolio
  data wrapped
=======
```
pytest tests/ -q
1380 passed, 0 failed   (1280 baseline + 100 new)

ruff check .
All checks passed!   (one F401 unused-import finding during
                       development, fixed before this count)
```

New test files: `tests/test_execution_state.py` (25),
`test_execution_metrics.py` (9), `test_execution_events.py` (9),
`test_execution_orchestrator.py` (34), `test_execution_api.py` (14).
Additive to existing files: `test_execution_coordinator.py` (+2),
`test_portfolio_ws.py` (+7).

## Known limitations / follow-up (documented, not hidden)

- No execution-outcome persistence yet — `ExecutionResult`/
  `ExecutionBatch` are in-memory only this phase (see architecture.md
  §21 "History updates").
- `signal_provider` (the entry/stop-loss/take-profit source
  `ExecutionOrchestrator` depends on) has no multi-symbol-capable
  implementation yet — `execution/strategy.py`'s existing
  `SMC_OI_Regime_Strategy` remains single-symbol-only and unmodified;
  this phase only defines and consumes the interface.
- Replacement handling closes the outgoing position only — it does not
  (and structurally cannot, without inventing sizing data) open the
  incoming side. That happens naturally on a later `decide()` cycle
  once capacity is freed.
- Paper-mode execution engines don't support targeted per-symbol close
  (a pre-existing, documented limitation of `execution_factory.py`, not
  something this phase changes) — `ExecutionOrchestrator` detects this
  via `hasattr(engine, "close_position")` and skips gracefully with a
  `CANCELLED` result rather than crashing.
- No dashboard panel consumes `/api/execution/*` or the new WS events
  yet.

See `MIGRATION.md` for upgrade/rollback notes.
>>>>>>> origin/feature/phase2e-execution-wiring
