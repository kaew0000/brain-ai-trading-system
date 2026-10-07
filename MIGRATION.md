# MIGRATION — SMC Analyst H4 BOS Symmetry

## Do you need to do anything?

No. No config, schema, API or dependency changes. No restart steps beyond
the normal deploy.

## Behavioural notes

- SHORT signals can now score up to 7/7 (previously 6/7), so SHORT
  confidence may be higher by 1/7 (~14 points) when H4 prints a bearish BOS.
- A bearish H4 BOS no longer adds to LONG scoring.
- If you have thresholds tuned against the old SHORT confidence ceiling,
  re-check them.

## Rollback

Revert the single commit; nothing is persisted by this change.
