# PATCH NOTES — Entry guard for already-open positions (V16 §98)

Branch: `fix/entry-existing-position-guard-s98`
Base: `main` at `9ef7bc1` (PR #138, §97 merged) · intended PR: #139
Commit: `fix(execution): refuse entry when a position is already open; emergency-close the filled qty (V16 §98)` (exactly one)

## Root cause
* R-03: `TradeManager.execute_trade()` ran `set_leverage` → `set_margin_type` → `cancel_all_orders()` with no check for an existing position. `cancel_open_orders(symbol)` removes the existing position's `closePosition` SL/TP, leaving it unprotected. Reachable whenever two code paths (legacy loop + scheduler, R-05) or a stale PortfolioState request an entry on a symbol that is already open.
* Emergency close used the signal `qty`; a partial entry fill makes a `reduceOnly` order of that size invalid, so the naked-position fallback could fail.

## Files
`execution/trade_manager.py`, `config/settings.py`, `tests/test_v16_s98_entry_position_guard.py`, docs.

## Impact
Entries on a symbol with an open position are now rejected (`success=False`, error `Entry refused: ...`) before any exchange write. One extra `get_position_risk(symbol)` call per entry. Flag: `ENTRY_EXISTING_POSITION_GUARD_ENABLED`.

## Not changed (needs owner decision)
R-04 fail-open commander gates, R-05 shared position state, R-06 API bind/token-in-URL, R-09 hedge mode, R-12 CloseSource inference.
