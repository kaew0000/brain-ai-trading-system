# MIGRATION — SMC Top-Down Confirmation / M5

## Do you need to do anything?

No. Defaults reproduce current behaviour: no M5 fetch, no new blocks.
No schema or dependency changes. Merge phases 1-4 in order.

## Opting in (`.env`, then restart)

1. `SMC_M5_ENABLED=True` — fetch/analyse M5 (extra API call per cycle; check rate limits).
2. `SMC_TF_CONFLICT_BLOCKS_TRADE=True` — skip when any timeframe's bias opposes the trade.
3. `SMC_TOPDOWN_GATE_ENABLED=True` — require the full sequence; expect far fewer trades.
   Adds `TOPDOWN_<state>` / `TF_CONFLICT` entries to `block_reasons` in the journal.

Recommended order: enable the M5 fetch and watch `topdown` in logged contexts first,
then the conflict block, then the full gate. Validate on testnet/paper before live capital.

## Related optional flags from earlier phases

`SMC_SWEEP_SCORING_ENABLED`, `SMC_CHOCH_REQUIRES_SWEEP`, `SMC_SWEEP_LEVELS_ENABLED`.
The top-down gate relies on sweep fields (always computed since phase 2).

## Rollback

Unset the flags (instant) or revert the commit. Nothing is persisted.
