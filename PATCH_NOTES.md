# PATCH NOTES — Multi-Symbol Reconciliation & Orphan Protection (V16 §62)

Branch: `feat/multi-symbol-reconciliation`
Base: `main` @ `9299ce7` (merge of PR #97, SCHEDULER_ENABLED implies dynamic symbols)

Closes the "Known follow-up" flagged in §60: position reconciliation
and orphan-position protection were single-symbol-hardcoded, so §60
left them disabled entirely under `SCHEDULER_ENABLED=true` rather than
run them with known-wrong data. This phase builds the real fix instead
of leaving them off.

## Root cause

`system_health/reconciliation.py::ReconciliationEngine._classify()`
was already symbol-agnostic (it only ever compares abstract
`has_position`/`side`/`qty` dicts) — what was hardcoded was the
data-gathering layer beneath it. `_read_exchange()`/`_read_bot()`/
`_read_journal()` all implicitly scoped to `settings.SYMBOL`, and the
suppression/buffer state was one set of instance attributes — meaning
only one position's worth of "have we already reported this" tracking
existed at all, regardless of how many symbols the multi-symbol
scheduler might actually have open at once.

`system_health/recovery_engine.py::RecoveryEngine` acted on
reconciliation's output with the same hardcoding, in three places:
- `_clear_ghost_journal_row()` / `_clear_runtime_ghost()` both used
  `settings.SYMBOL` directly, regardless of which symbol the mismatch
  was actually about.
- `_protect_orphaned_exchange_position()` already correctly read
  `symbol = pos.get("symbol")` from the exchange response, but never
  used it — `dp.get_position_info()` (no symbol arg) could only ever
  discover an orphan in the provider's own default symbol, and SL
  placement went through `tm.place_stop_loss(...)` with no symbol
  either, which — traced through `execution/execution_coordinator.py`'s
  `ExecutionCoordinator.__getattr__` — silently falls through to
  `get_manager()` with no argument, i.e. the *wrong* symbol's
  `TradeManager` (and therefore its lot-size/precision filters) for
  anything but the default symbol.
- `self._orphan_hold` was a single dict, not one per symbol — two
  simultaneously orphaned positions in different symbols could only
  ever be tracked one at a time.

## Fix

**`system_health/reconciliation.py`** (rewritten, additive):
- `ReconciliationEvent` gained a `symbol` field.
- `_read_exchange`/`_read_bot`/`_read_journal` now accept an optional
  `symbol` parameter (default: `settings.SYMBOL`, so `run()` — the
  classic single-symbol path — is byte-for-byte unchanged; confirmed
  by re-running all 69 pre-existing reconciliation/recovery/ghost
  tests unmodified).
- New `run_all_symbols(sys)`: discovers every symbol appearing across
  open exchange positions (`data_provider.get_all_positions()`, added
  in §60), open journal trades, and `portfolio_state.held_symbols()` —
  the union, since a symbol missing from every view by definition
  isn't a mismatch — and runs the identical `_classify()` logic once
  per symbol, each with its own independent suppression state (a
  mismatch on one symbol publishing/suppressing doesn't affect a
  different symbol's tracking).
- Internal state (`_buf`, `last_fired_sig`, etc.) refactored into a
  `dict[key, _SymbolState]`, keyed by symbol for the multi-symbol path
  and a private sentinel key for `run()`'s own state — `get_recent()`/
  `status()`/`get_last_views()` (the pre-existing single-view API)
  read only that sentinel key, unchanged in observable behavior. New
  `get_recent_for_symbol()`/`status_all_symbols()`/
  `get_last_views_for_symbol()` expose the full multi-symbol view.

**`system_health/recovery_engine.py`**:
- `attempt_reconciliation_recovery()` now reads `event.symbol`
  (falling back to `settings.SYMBOL` for events from the classic
  `run()` path, which predate this field) and threads it through.
- `_clear_ghost_journal_row()` / `_clear_runtime_ghost()` use the real
  symbol instead of a hardcoded `settings.SYMBOL`.
- `_protect_orphaned_exchange_position()`: `dp.get_position_info(symbol=...)`
  can now find an orphan in any symbol. SL placement routes through
  `tm.get_manager(symbol)` when `tm` is symbol-aware (an
  `ExecutionCoordinator`), falling back to calling `tm` directly when
  it isn't (a plain `TradeManager`, matching pre-§62 behavior exactly).
- `self._orphan_hold` → `self._orphan_holds: dict[symbol, dict]`.
  `get_orphan_hold()` (singular) kept for backward compatibility,
  returning one of the holds. New `get_orphan_holds()` (plural) exposes
  all of them. `acknowledge_orphaned_position()` gained an optional
  `symbol` parameter — omitted, it clears every held orphan (the exact
  pre-§62 zero-arg behavior); given, it clears just that one. The
  risk_engine manual hold is only cleared once `_orphan_holds` is
  empty — acknowledging one symbol's orphan must not silently resume
  trading while a *different* symbol's orphan is still unprotected.

**`main.py`**:
- `run_position_reconciliation()` now calls
  `engine.run_all_symbols(sys)` under `SCHEDULER_ENABLED=true`,
  `engine.run(sys)` otherwise (unchanged). Scheduled unconditionally
  again (previously disabled entirely under `SCHEDULER_ENABLED=true`
  by §60, pending this fix).
- `run_ghost_reconciliation_check()` (Track C3 Phase 2, off by
  default) is **still not scheduled** under `SCHEDULER_ENABLED=true` —
  its `OrderStateManager` dependency was not touched by this phase and
  remains single-symbol-hardcoded. See Known follow-up.

**`api/app.py`**:
- `GET /api/system/reconciliation` — added `orphan_holds` (plural,
  full list) and `status_by_symbol` alongside the existing `orphan_hold`
  (kept, backward compatible).
- `POST /api/system/reconciliation/acknowledge` — accepts an optional
  body `{"symbol": "XRPUSDT"}` to acknowledge just that symbol; omitted
  body clears everything (pre-§62 behavior).

## Known follow-up (not this phase — flagged, not built)

`run_ghost_reconciliation_check()` / `system_health/ghost_reconciliation.py`'s
`GhostReconciliationMonitor` goes through `system_health/order_state.py`'s
`OrderStateManager`, which still only ever checks `settings.SYMBOL` —
not touched by this phase. Left un-scheduled under
`SCHEDULER_ENABLED=true`, same reasoning §60 originally applied to
both jobs, now narrowed to just this one. It's off by default even in
single-symbol mode (`ORDER_RECONCILIATION_ENABLED`), so this is a
smaller, lower-priority remaining gap than the always-on job this
phase fixes.

## Tests

New: `tests/test_multi_symbol_reconciliation.py` — 28 tests: symbol
discovery (each of the three sources, union/dedup, one source failing
doesn't block the others), two symbols mismatching simultaneously are
each tracked/suppressed independently, `DUPLICATE_JOURNAL_TRADES` is
correctly scoped per symbol (two *different* symbols each having one
open trade is not a duplicate), multi-symbol accessors stay isolated
from `run()`'s own state, `ReconciliationEvent.symbol` is populated
correctly on both paths, ghost-clearing uses the real symbol,
orphan-protection routes SL placement to the symbol-correct manager
(and falls back correctly when `tm` isn't symbol-aware), multiple
simultaneous orphan holds are tracked/acknowledged independently
(including the "don't resume trading while another orphan remains"
invariant), `main.py`'s dispatch, and the two API endpoint extensions.

Updated: `tests/test_recovery_engine.py` — 6 `tm = MagicMock()` calls
in `TestOrphanedExchangePosition` changed to
`MagicMock(spec=["place_stop_loss"])` — an unspecced `MagicMock` makes
`hasattr(tm, "get_manager")` true (attribute auto-vivification), which
made every test in that class silently route through a *different*
child mock instead of the one being asserted against. Fixed to
accurately reflect real `TradeManager`'s shape (no `get_manager` —
only `ExecutionCoordinator` has that). All 19 tests in that file pass
unchanged in outcome.

Full suite: `pytest tests/` → **3096 passed** (up from 3068), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on every changed source file.
`python -c "import main"` → succeeds.

## Files changed

`system_health/reconciliation.py` (rewritten),
`system_health/recovery_engine.py`, `main.py`, `api/app.py`,
`tests/test_recovery_engine.py`,
`tests/test_multi_symbol_reconciliation.py` (new), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`, `docs/architecture.md` (§62).
