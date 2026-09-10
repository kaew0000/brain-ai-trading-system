# PATCH NOTES — Multi-Symbol Scheduler Safety (V16 §60)

Branch: `fix/multi-symbol-scheduler-safety`
Base: `main` @ `e59e340` (merge of PR #95, CORS deny-by-default)

## Context

Triggered by a request to switch from a single fixed symbol (BTCUSDT
— its 50 USDT Binance minimum notional doesn't size well against a
$20 account) to true multi-symbol auto-selection
(`SCANNER_ENABLED`+`SCHEDULER_ENABLED`, both existing but never
enabled in live production). Before recommending "just flip the
flags," traced what would actually happen, since this is a path that
has never run live before. Found three real problems, none of them
config — all in code that's been sitting dormant.

## Root causes found

**1. No mutual exclusion between the classic loop and the scheduler.**
`main.py::main()` scheduled `run_trading_cycle()` (the classic
single-symbol loop, fixed to `settings.SYMBOL`) unconditionally via
the cooperative `schedule` library, with no guard for
`SCHEDULER_ENABLED`. `ExecutionScheduler` (built and started inside
`build_system()` when `SCHEDULER_ENABLED=true`) runs on its own
genuinely separate daemon thread
(`execution/execution_scheduler.py::start()`). Enabling
`SCHEDULER_ENABLED` alone would have left both running concurrently —
two independent, uncoordinated decision-makers acting on the same
balance/`risk_engine`/journal, with no lock between them.

**2. `monitor_open_trades()` (scheduled every 30s, unconditionally)
could mark a genuinely-still-open position CLOSED.** It called
`data_provider.get_position_info()` with no symbol — which, tracing
into `data/binance_provider.py`, was hardcoded to query only
`self.symbol` (the provider's single configured default, i.e.
`settings.SYMBOL`). With more than one symbol capable of being open
at once (the whole point of multi-symbol trading), a genuinely open
position in any symbol *other than* `settings.SYMBOL` would read as
"no position" — and this function would then walk every open journal
row (`get_open_trades()`, not filtered by symbol) and mark all of them
CLOSED, computing a WIN/LOSS result and PnL against a mark price for
the wrong reasons, while the real position stayed open on the
exchange. A real data-corruption bug, not merely an incomplete
feature.

**3. `run_position_reconciliation()` has the identical read path, and
compounds the risk.** `system_health/reconciliation.py::
ReconciliationEngine._read_exchange()` also calls
`get_position_info()` with no symbol, feeding a single-position data
model (`has_position: bool`, one `side`, one `qty`). Worse:
`system_health/recovery_engine.py::attempt_reconciliation_recovery()`
treats the exchange as root authority — when its (wrongly-scoped)
exchange view says flat, it **auto-clears** any journal or runtime
record still claiming a position, believing it's a stale "ghost." A
real, open position in a non-default symbol would trigger exactly
this: an active position's journal record deleted by the recovery
engine itself, purely because the wrong symbol was checked.

## Fix

**`data/binance_provider.py`**
- `get_position_info(self, symbol: str | None = None)` — added an
  optional `symbol` param (default: `self.symbol`, i.e. every existing
  call site is unaffected — confirmed by running all 426
  previously-passing tests across every file that touches this method
  or `monitor_open_trades()` unchanged and green).
- New `get_all_positions(self) -> list[dict]` — one call to Binance's
  `/fapi/v2/positionRisk` with no symbol filter, returning every
  symbol currently holding a non-zero position.

**`main.py`**
- `main()`'s scheduling block: `run_trading_cycle` is now only
  registered when `SCHEDULER_ENABLED=False`. When true, logs why and
  leaves the scheduler as the sole source of new trade decisions.
- `monitor_open_trades()`: new branch for `SCHEDULER_ENABLED=True` —
  fetches every open exchange position once via `get_all_positions()`,
  then checks each open journal row against **its own** symbol rather
  than the single default. Per-symbol mark price is fetched (and
  cached per symbol per call) only for rows that actually need
  closing. `SCHEDULER_ENABLED=False` path is untouched, byte-for-byte.
- `run_position_reconciliation` and `run_ghost_reconciliation_check`:
  **not scheduled at all** when `SCHEDULER_ENABLED=True`, logged as a
  warning at startup. Given the recovery engine's auto-clear behavior
  above, running this with known-wrong (single-symbol) data is
  actively worse than not running it — this is a deliberate safety
  choice, not an oversight. See Known follow-up.

## Known follow-up (not this phase — flagged, not built)

**No multi-symbol-aware position reconciliation exists yet.**
`ReconciliationEngine`'s entire data model (`has_position: bool`, one
`side`, one `qty`) is single-position-shaped throughout — mismatch
classification, recovery actions, event-bus publishing, and
repeat-fire suppression are all built around exactly one position.
Making this properly multi-symbol-aware is a real redesign of that
class, not a small patch, and was out of scope to do safely in the
same phase as the fixes above. Practical effect: while running in
scheduler mode, an orphaned exchange position (one that exists on
Binance but has no journal record — e.g. opened before this bot
session) will **not** get auto-protected with a stop-loss the way
`_protect_orphaned_exchange_position()` already does for the
single-symbol path. Recommend treating this as the next phase before
running scheduler mode unattended for extended periods.

**Flags are not flipped by this patch.** Per this project's own
established posture (every dormant feature stays off until an
operator deliberately opts in after reading the migration notes —
`SCHEDULER_ENABLED`, `MODEL_PROMOTION_REQUIRES_APPROVAL`, etc.), this
phase makes the scheduler path *safe* to enable; it does not enable
it. See MIGRATION.md for exactly what to set.

## Tests

New: `tests/test_multi_symbol_position_tracking.py` — 13 tests:
- `get_position_info(symbol=...)` — defaults unchanged, explicit
  symbol overrides, no-position-for-that-symbol returns `None`.
- `get_all_positions()` — returns every non-zero symbol (flat symbols
  excluded), no symbol filter sent to the exchange call, empty account
  → empty list.
- `monitor_open_trades()` scheduler-mode branch (via the real
  production function, fake data provider/journal): a position open in
  a different symbol is left alone (the core bug); only the symbol
  that actually closed gets processed; per-symbol mark price is used
  correctly for PnL, not a shared/wrong value; mark price is fetched
  once per symbol even with multiple open rows for the same symbol;
  nothing-to-process short-circuits without touching the journal or
  fetching any mark price; no-open-trades short-circuits before even
  calling `get_all_positions()`.
- Regression guard: `SCHEDULER_ENABLED=False` never calls
  `get_all_positions()` — the pre-§60 single-symbol path is untouched.

Also re-ran all 426 pre-existing tests across every file touching
`get_position_info`/`monitor_open_trades`
(`test_mission_pipeline_integration.py`, `test_trade_lifecycle_
integration.py`, `test_close_orphaned_position.py`, `test_commander.py`,
`test_ghost_reconciliation*.py`, `test_order_state*.py`,
`test_phase3_complete.py`, `test_reconciliation.py`, `test_recovery_
engine.py`, `test_w14_2a_attribution_wiring.py`, `test_audit_fixes.py`)
— all green, confirming the `symbol=None` default preserves existing
behavior exactly.

Full suite: `pytest tests/` → **3066 passed** (up from 3053), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` on the two changed source files → clean
(one pre-existing, unrelated `main.py:76` finding — the `frame`
parameter of a signal handler — confirmed identical on unmodified
`main`, not introduced here). `python -c "import main"` → succeeds.

**Not automated:** the `main()` scheduling-block change itself (which
job gets registered under which flag) isn't covered by an automated
test — `main()` is a large, side-effecting entry point (signal
handlers, `build_system()`, starts the API server and browser) not
designed for unit testing, and building a harness for it would be a
significant, unrelated refactor. Verified by direct code review; the
change is a small, self-evidently-correct `if/else` around existing
`schedule.every(...).do(...)` calls.

## Files changed

`data/binance_provider.py`, `main.py`,
`tests/test_multi_symbol_position_tracking.py` (new), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`, `docs/architecture.md` (§60).
