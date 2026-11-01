# PATCH NOTES — Failed orders no longer journaled OPEN → phantom LOSS (V16 §96)

Branch: `fix/failed-trade-phantom-loss-s96`
Base: `main` at `45fc675` (PR #136, §95 merged) · intended PR: #137
Commit: `fix(execution): failed orders no longer journaled OPEN / phantom LOSS (V16 §96)` (exactly one)

## Root cause (reproduced by test before the change)
`TradeRecord.from_decision()` always starts a row as `OPEN`; `main.run_trading_cycle` saved it even when `execute_trade()` failed (qty 0). `monitor_open_trades()` then
saw "OPEN row, no position on exchange" and settled it as WIN/LOSS from the mark price (→ LOSS). `JournalV2.get_consecutive_losses()` counts it, so three failed orders
(margin, minQty, SL-failed emergency close) tripped the consecutive-loss gate with no real loss. `test_three_failed_orders_do_not_trip_loss_streak` fails on the old code.

## Files
`main.py`, `execution/trade_manager.py`, `tests/test_v16_s96_failed_trade_phantom_loss.py`, `docs/V16_BUG_AUDIT_S96.md` (full bug list + hand-off), `CHANGELOG.md`,
`docs/architecture.md` (§96), `MIGRATION.md`, this file.

## Impact
Failed executions are stored `CANCELLED` (already excluded from daily stats); monitor heals existing `OPEN` rows with `quantity<=0` to `CANCELLED`; a failed emergency close is
reported honestly (`NAKED POSITION STILL OPEN`, `result["naked_position_open"]=True`); `-4116` recognised as duplicate clientOrderId. No schema/config/API change. Successful
trades and the SL-failure-with-successful-close message are unchanged.

## Verification
Baseline 3560 passed / 3 failed → after 3569 passed / 3 failed (same 3 `tests/test_dashboard_serving.py` failures: need a built `dashboard/`). ruff clean on changed files.

## Not changed / limitations
Open items R-01..R-11 are listed with fixes in `docs/V16_BUG_AUDIT_S96.md` (notably: outcome is still a mark-price heuristic; journal still stores the signal price, not the fill).
`-4116` is from memory of Binance's futures error table and unverified. No live exchange was used. 3 pre-existing failures in `tests/test_dashboard_serving.py` need a built `dashboard/`.
