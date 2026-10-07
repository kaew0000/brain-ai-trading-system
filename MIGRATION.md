# MIGRATION — Sweep-Anchored Levels

## Do you need to do anything?

No. Defaults reproduce the previous levels exactly. Requires phase 2
(sweep fields in the SMC context); merge phases in order.

## Opting in

`SMC_SWEEP_LEVELS_ENABLED=True` in `.env`, restart. Optional tuning:
`SMC_SWEEP_SL_BUFFER_PCT`, `SMC_SWEEP_MAX_SL_PCT`, `SMC_SWEEP_MIN_RR`,
`SMC_SWEEP_FALLBACK_RR`. Validate on testnet/paper first: stop distance
now varies per trade, which changes position size and risk-per-trade
outcomes; with real capital, check the minimum-notional impact too.

## Rollback

Unset the flag (instant) or revert the commit. Nothing is persisted.
