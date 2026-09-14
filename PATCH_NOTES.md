# PATCH NOTES — SL-Distance-Zero: Skip, Not Clamp (V16 §64)

Branch: `fix/sl-distance-zero-skip-not-clamp`
Base: `main` @ `fae1038` (merge of PR #99, N+1 query fix)

## Root cause

`execution/trade_manager.py::calculate_position_size()`, when
`stop_loss == entry_price` (`sl_dist == 0`, a degenerate signal that
can't produce a meaningful risk-based size), returned
`self._round_qty(0.001)` — a hardcoded quantity.

Two problems, found during this week's broader audit:
1. **Wrong for any symbol but BTCUSDT.** `0.001` is roughly $60-100
   notional at typical BTC prices; for a cheaper-priced symbol (now
   tradeable via §60–§62's multi-symbol work) it could be a wildly
   different, unintended notional.
2. **Directly violates this exact function's own documented policy.**
   `_round_qty()`'s own docstring says outright: *"this method must
   NEVER be used as the position-sizing decision itself... calculate_
   position_size() below uses _floor_to_step() directly and returns
   0.0 (skip trade) instead of clamping."* Every other unsizeable-
   quantity path in this same function (margin-capped below minQty,
   raw qty below minQty, raw qty that floors below minQty) already
   returns `0.0` for exactly this reason (see the `BUG-LIVE-RISK-04`
   comment a few lines below the fixed branch) — the `sl_dist == 0`
   branch was the one path in this function that didn't follow its own
   rule.

## Fix

`sl_dist == 0` now returns `0.0` (skip the trade), matching every
other unsizeable-quantity case in this function. `execute_trade()`'s
existing `if qty <= 0: raise ValueError` already treats `0.0` as
"cannot size" — no new handling needed anywhere downstream, same
convention `TestQuantitySkipInsteadOfClamp` already exercises for
every other case.

## Tests

- `tests/test_live_money_safety.py::TestQuantitySkipInsteadOfClamp` —
  new `test_case_g_sl_distance_zero_is_rejected_not_defaulted`,
  matching that class's existing lettered convention (a–f already
  covered every other unsizeable path; this was the missing case).
- `tests/test_execution.py::TestTradeManager::test_position_size_
  zero_sl_distance` — updated: asserted the old `0.001` behavior,
  now asserts `0.0`. This is the one pre-existing test that encoded
  the bug as expected behavior; corrected, not removed.

Full suite: `pytest tests/` → **3106 passed** (up from 3105), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on the changed file.
`python -c "import main"` → succeeds.

## Files changed

`execution/trade_manager.py`, `tests/test_execution.py`,
`tests/test_live_money_safety.py`, `PATCH_NOTES.md`, `MIGRATION.md`,
`CHANGELOG.md`, `docs/architecture.md` (§64).
