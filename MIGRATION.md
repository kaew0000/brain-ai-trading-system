# MIGRATION — V16 Phase 4C: Symbol-Aware SMC/OI Regime Strategy Adapter

## Do you need to do anything?

**No — this phase is purely additive.** No settings changed, no schema
changed, no existing behavior changed. `config/settings.py`'s
`STRATEGY_NAME` default stays `"portfolio_signal_provider"`; the live
bot's behavior is identical before and after this bundle is imported
unless you deliberately opt in below.

## Opting in (optional)

A new strategy name, `"smc_oi_regime_multi"`, is now available wherever
`STRATEGY_NAME` is read (`config/settings.py` / `.env`). It is safe to
select for `ExecutionScheduler`'s multi-symbol path — unlike the
existing `"smc_oi_regime"`, which is not and remains unchanged.

```
STRATEGY_NAME=smc_oi_regime_multi
```

Only set this if you specifically want `ExecutionScheduler` to run the
`BrainDecisionEngine`/SMC-OI-regime pipeline per-symbol instead of the
default `"portfolio_signal_provider"` pipeline. The two strategies use
different decision logic (see `execution/strategy_registry.py`'s module
docstring for both) and are not expected to produce identical signals
for the same symbol/market conditions — this is a deliberate strategy
choice, not a drop-in upgrade.

No database changes. No new dependencies. No frontend changes (Track A
only this phase).

## Rollback

Revert `execution/strategy_registry.py` and delete
`execution/smc_oi_regime_multi.py` and
`tests/test_smc_oi_regime_multi.py`. If you set
`STRATEGY_NAME=smc_oi_regime_multi` in `.env`, remove it (or set it back
to `portfolio_signal_provider`) before rolling back the code, since an
unrecognized `STRATEGY_NAME` will raise `KeyError: Unknown strategy` at
`main.py`'s bootstrap.

## What this does not fix

See `PATCH_NOTES.md`'s "What this does not fix / does not do" for the
full list of deliberate, reasoned-through scope boundaries (the
pre-existing `dashboard_src/dist` build gap, the unchanged
`"smc_oi_regime"` legacy adapter, the unchanged live default).
