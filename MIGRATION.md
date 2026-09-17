# MIGRATION — Commission/Fee Backfill (V16 §67)

## Do you need to do anything?

**No, if `FEE_BACKFILL_ENABLED=false` (the default).** No new
behavior runs, no Binance API calls are made, and
`journal.save_execution_attribution()` is never invoked by this
feature in that state — byte-identical to before this phase.

## If you want fee data backfilled

Set `FEE_BACKFILL_ENABLED=true` in your `.env`. On the configured
interval (`FEE_BACKFILL_INTERVAL_MINUTES`, default 15 minutes), a
background job will:

- Look back `FEE_BACKFILL_LOOKBACK_HOURS` (default 24h) for trades
  missing fee data.
- Fetch each trade's entry commission from Binance
  (`GET /fapi/v1/userTrades`) and write it to
  `trades.extra_data.attribution.fees_entry` (and `.fees` when the
  full picture is known).
- Fetch exit commission too, but **only** for trades whose close order
  was placed by the multi-symbol scheduler's replacement-close path.
  Trades closed via the classic single-symbol loop's TP/SL detection
  will only ever get an entry fee backfilled — there is no close
  `orderId` recorded anywhere for that path to fetch against, and this
  job does not guess. This is a permanent limitation of this design,
  not a rollout-phase gap.
- Cap itself at `FEE_BACKFILL_MAX_TRADES_PER_RUN` (default 50)
  Binance API calls per run.

No database migration — `fees_entry`/`fees_exit`/`fees` are written
into the existing `trades.extra_data` JSON column via the existing
`save_execution_attribution()` merge method, the same mechanism every
other execution-attribution field already uses. Nothing to run before
enabling; old trades within the lookback window are picked up
automatically the first time the job runs.

**Requires** your Binance API key to have permission for
`GET /fapi/v1/userTrades` (standard USER_DATA scope — the same
permission level the bot already needs for existing account/position
calls).

## Rollback

Set `FEE_BACKFILL_ENABLED=false` (or unset it) and restart. No
database migration either direction — any `fees_entry`/`fees_exit`/
`fees` values already backfilled remain in `trades.extra_data`
unchanged; they simply stop being updated.
