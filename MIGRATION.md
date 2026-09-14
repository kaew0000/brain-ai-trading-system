# MIGRATION — Enforce scheduler_safe Strategy Selection (V16 §65)

## Do you need to do anything?

**No, in the overwhelming majority of cases.** `STRATEGY_NAME` defaults
to `"portfolio_signal_provider"`, which is (and always was)
scheduler-safe. Nothing changes for the default configuration.

## If you have `STRATEGY_NAME=smc_oi_regime` set explicitly

**And also `SCHEDULER_ENABLED=true`:** the scheduler will no longer
start. Previously this combination ran silently with cross-symbol-
contaminated regime data (every classification reflected whichever
symbol the data provider happened to be globally configured with, not
the actual candidate symbol being evaluated) — now it's refused, with
a clear `ERROR`-level log line explaining why and what to use instead
(`portfolio_signal_provider` or `smc_oi_regime_multi`).

**And `SCHEDULER_ENABLED=false`:** no change — `smc_oi_regime` remains
fully usable for the classic single-symbol loop, which is exactly the
"future single-symbol standalone use" it was kept registered for.

## Rollback

Revert this branch and restart. `scheduler_safe` stops being enforced
— `STRATEGY_NAME=smc_oi_regime` + `SCHEDULER_ENABLED=true` would once
again start silently (not recommended; this is the exact combination
this patch exists to prevent).
