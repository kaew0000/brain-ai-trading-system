# MIGRATION — Fix N+1 Query in Ensemble Learning Dataset (V16 §63)

## Do you need to do anything?

**No.** Pure performance fix, no config changes, no schema changes, no
behavior changes — `get_ensemble_learning_dataset()` and
`get_trade_attribution()` return exactly the same data as before,
verified with direct equality assertions, not just "should be
equivalent" reasoning. Restart isn't even strictly required (nothing
about running state changes), but normal deploy practice applies as
usual.

## What actually changes

Anything that calls `get_ensemble_learning_dataset()` — the training
dataset export used by `research/dataset_builder.py` and (per
`docs/architecture.md` §29) intended for a future Phase 4C learning
consumer — gets a response in roughly constant time regardless of how
many closed trades exist, instead of scaling linearly with trade
count. At 2,000 trades: ~0.08s (measured). The old per-row pattern was
previously measured at ~28.5s at 10,000 trades; this account's trade
volume is nowhere near that yet, but multi-symbol trading (§60–§62)
means it'll get there faster than the single-symbol loop would have.

## Rollback

Revert this branch and restart. `get_ensemble_learning_dataset()`
reverts to calling `get_trade_attribution()` once per row (O(N)
queries) — same output, slower at scale. No data involved either
direction.
