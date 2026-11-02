# PATCH NOTES — Real fill & real exit outcome in the journal (V16 §97)

Branch: `fix/real-fill-and-realized-pnl-s97`
Base: `main` at `0a99e76` (PR #137, §96 merged) · intended PR: #138
Commit: `fix(journal): record the real entry fill and the real closed-trade outcome (V16 §97)` (exactly one)

## Problem
* R-02: the journal and `TRADE_EXECUTED` used the signal's price/qty. USDS-M market orders are acked before they are priced, so slippage and partial fills were invisible and R-multiples skewed.
* R-01: `monitor_open_trades()` decided WIN/LOSS from the mark price when it noticed the position was gone (TP hit + pullback ⇒ LOSS), priced the trade at that mark and ignored fees. That outcome feeds RiskEngine's consecutive-loss gate and the learning pipeline.
* Side effect of §96: when every OPEN row was healed by `qty<=0 → continue`, the mission-close block hit unbound variables and still cleared `current_mission_id`.

## Files
`execution/trade_manager.py`, `analytics/trade_journal.py`, `execution/execution_orchestrator.py`, `main.py`, **new** `journal/exit_truth.py`, **new** `tests/test_v16_s97_real_fill_and_exit.py`, `tests/test_execution_orchestrator.py` (+3), `docs/V16_BUG_AUDIT_S97.md`, `CHANGELOG.md`, `docs/architecture.md` (§97), `MIGRATION.md`, this file.

## Behaviour
Entry: real `avgPrice/executedQty` read back (response, else ≤3 `query_order` polls); journaled instead of signal price/qty; `fill_price/filled_qty/fill_confirmed/slippage_pct` added to the execute result; terminal-unfilled entry aborts before SL; read-back failure ⇒ unchanged behaviour. Exit: outcome/exit price/PnL from the trade's real fills (`journal/exit_truth.py`, PnL net of commissions), mark-price heuristic only as fallback.

## Verification
Baseline (main @ 0a99e76 + §96) 3569 passed / 3 failed → after **3596 passed / 3 failed** (same 3 in `tests/test_dashboard_serving.py`: need a built `dashboard/`). 8 of the 24 new tests fail on the pre-§97 code (incl. "TP hit then pullback is still a WIN"). `ruff` clean on changed files.

## Not verified / not changed
No live or testnet exchange was available: ACK-style market response, `userTrades` field names and its 7-day window are from Binance docs/memory — verify on testnet before trusting outcomes. Open items R-03..R-12 are in `docs/V16_BUG_AUDIT_S97.md`.
