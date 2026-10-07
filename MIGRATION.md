# MIGRATION — SMC Liquidity Sweep

## Do you need to do anything?

No. Defaults keep existing scoring and signals unchanged. No schema or
dependency changes.

## Opting in (set in `.env`, restart the bot)

- `SMC_SWEEP_SCORING_ENABLED=True` — sweep adds a scoring point; SMC
  confidence is then computed over 8 points instead of 7, so absolute
  confidence values shift slightly.
- `SMC_CHOCH_REQUIRES_SWEEP=True` — CHoCH only scores after a
  same-direction sweep; expect fewer SMC signals.

Test on testnet/paper first and re-check any thresholds tuned on SMC confidence.

## Notes

- Context dicts gain new `smc_*` keys (`sweep*`); consumers using `.get`
  are unaffected.
- SMCAnalyst factor verdicts for BOS/CHoCH/FVG/OB now read `SUPPORTS`
  correctly (previously `OPPOSES`); display only.
- Rollback: revert the commit; nothing is persisted.
