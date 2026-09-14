# MIGRATION — SL-Distance-Zero: Skip, Not Clamp (V16 §64)

## Do you need to do anything?

**No.** No config changes. Restart after merging as usual.

## What changes in behavior

Only for the specific degenerate case where a signal's `stop_loss`
exactly equals its `entry_price` — extremely rare, and arguably
indicates a bug further upstream in signal generation if it happens at
all. Previously: the trade would size to a hardcoded 0.001-unit
quantity regardless of symbol. Now: the trade is skipped (logged as
`PositionSize SKIPPED`), same as every other case where this account's
risk/margin policy can't support a valid size. No behavior change for
any normal signal where `stop_loss != entry_price`.

## Rollback

Revert this branch and restart. `sl_dist == 0` goes back to returning
a hardcoded `0.001`-unit quantity instead of skipping the trade.
