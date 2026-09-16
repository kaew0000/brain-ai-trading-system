# PATCH NOTES — Multi-Symbol Order State & Ghost Reconciliation (V16 §66)

Branch: `feat/multi-symbol-ghost-reconciliation`
Base: `main` @ `0e05f1a` (merge of PR #101, scheduler_safe enforcement)

Closes the last item flagged in §62's "Known follow-up":
`run_ghost_reconciliation_check()` / `OrderStateManager` remained
single-symbol-only after §62 fixed `ReconciliationEngine` itself. This
phase closes it — this was the last remaining item from this week's
broader gap-analysis audit that qualifies as a genuine bug (not a
brand-new feature build).

## Root cause

`system_health/order_state.py::OrderStateManager.get_order_state(sys,
symbol=...)` — and `system_health/ghost_reconciliation.py::
GhostReconciliationMonitor.check(sys, symbol=...)`, which calls it —
already accepted an optional `symbol` parameter throughout the whole
call chain. The plumbing existed. What was broken: internally,
`get_order_state()` always called `ReconciliationEngine.run(sys)` and
`get_last_views()` — which (per `reconciliation.py`'s own docstring,
and §62's design) only ever read/write `run()`'s own
`settings.SYMBOL`-keyed state, regardless of what `symbol` argument
was passed in.

Concretely: `get_order_state(sys, symbol="XRPUSDT")` would silently
return **BTCUSDT's** `exchange_position`/`journal_position`/
`runtime_position`, mislabeled with `symbol="XRPUSDT"` in the returned
snapshot. Worse than simply unimplemented — it looks correct without
being correct.

`main.py::run_ghost_reconciliation_check()` compounded this: it called
`monitor.check(sys)` with no symbol at all (implicitly
`settings.SYMBOL` only), so even with `OrderStateManager` fixed, the
scheduled job itself would never have asked about any other symbol.

## Fix

`system_health/reconciliation.py` — new
`run_for_symbol(sys, symbol) -> ReconciliationEvent | None`: reconciles
exactly one caller-specified symbol using the same per-symbol keyed
state `run_all_symbols()` (§62) already uses, so a symbol queried both
ways shares one suppression track rather than two independent ones.

`system_health/order_state.py::get_order_state()` — now branches on
`settings.SCHEDULER_ENABLED`: under scheduler mode, calls
`reconciliation.run_for_symbol(sys, symbol)` /
`get_last_views_for_symbol(symbol)` instead of `run(sys)` /
`get_last_views()`. `SCHEDULER_ENABLED=false` path is byte-for-byte
unchanged.

`main.py::run_ghost_reconciliation_check()` — under
`SCHEDULER_ENABLED=true`, discovers every symbol
`ReconciliationEngine._discover_symbols()` finds (the same discovery
`run_position_reconciliation()`'s own `run_all_symbols()` call already
uses) and calls `monitor.check(sys, symbol=s)` once per symbol, instead
of a single implicit-default call. `SCHEDULER_ENABLED=false` path
unchanged. The scheduling block itself no longer excludes this job
under scheduler mode (previously left un-scheduled entirely, per §62's
"known-wrong data is worse than no data" reasoning — no longer
needed, since the data is now correct).

## Tests

New: `tests/test_ghost_reconciliation_multi_symbol.py` — 9 tests:
`run_for_symbol()` reconciles only the given symbol and shares
suppression state with `run_all_symbols()`; the core bug fix itself
(`get_order_state()` under scheduler mode reflects the *requested*
symbol's real exchange/journal state, not `settings.SYMBOL`'s,
confirmed with `settings.SYMBOL != "XRPUSDT"` as an explicit sanity
check against a coincidental pass); two symbols queried independently
return independently correct snapshots; `SCHEDULER_ENABLED=false` is
an unchanged regression guard (never calls `get_all_positions()`);
`main.py`'s dispatch checks every discovered symbol under scheduler
mode, checks once with no symbol otherwise, and checks nothing when no
symbols are discovered.

All 120 pre-existing tests across every file touching the changed
modules (`test_ghost_reconciliation.py`, `test_ghost_reconciliation_
api.py`, `test_order_state.py`, `test_order_state_api.py`,
`test_multi_symbol_reconciliation.py`, `test_reconciliation.py`,
`test_recovery_engine.py`) pass unchanged.

Full suite: `pytest tests/` → **3121 passed** (up from 3112), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on every changed source file (one
pre-existing, unrelated finding — `main.py`'s signal-handler `frame`
parameter, confirmed identical on unmodified `main` in every prior
phase this week that touched this file).
`python -c "import main"` → succeeds.

## Files changed

`system_health/reconciliation.py`, `system_health/order_state.py`,
`main.py`, `tests/test_ghost_reconciliation_multi_symbol.py` (new),
`PATCH_NOTES.md`, `MIGRATION.md`, `CHANGELOG.md`,
`docs/architecture.md` (§66).
