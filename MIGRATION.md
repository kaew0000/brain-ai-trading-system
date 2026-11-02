# MIGRATION — Real fill & real exit outcome (V16 §97)

## Required
None. No schema, config or API change.

## What you will notice
- New trades are journaled at the exchange's real average fill price and filled quantity (when it can be read back); `TRADE_EXECUTED` shows `entry_price` (real), `signal_price`, `slippage_pct`.
- A closed trade's `result`, `exit_price` and `pnl` come from the trade's actual Binance fills. `pnl` is now **net of commissions** (it was gross, mark-based). Trades that cannot be resolved from fills keep the old mark-price heuristic.
- Expect a few extra read-only Binance calls per entry (`query_order`, at most 3) and per close (`userTrades` ×2).
- Historic rows are not rewritten; statistics mix mark-based (old) and fill-based (new) outcomes across the upgrade date.

## Verify after deploying (testnet first)
Open one trade and check the journal row against the Binance order/trade history: entry price = average fill, closed `pnl` ≈ realized PnL − commissions.

## Rollback
`git revert` the commit. No data migration to undo.
