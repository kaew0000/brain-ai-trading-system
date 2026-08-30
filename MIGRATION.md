# MIGRATION — Fix: Training Lane Position TIMEOUT Firing at ~32 Minutes Instead of ~24 Hours

## Do you need to do anything?

**No action required to get the fix.** The new setting
`BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS` defaults to `24.0` and is
picked up automatically on the next restart — no `.env` change needed
unless you want a different timeout window than 24 hours.

## What changes in behavior after this restart

- The Background Training Lane (Track C) will hold a position open for
  up to ~24 real hours (its actual intended behavior) instead of
  force-closing it after ~32 minutes.
- Any position that was already open in this lane when you restart is
  restored via `TrainingLaneRunner._restore_state()` and will pick up
  the newly-calibrated timeout automatically — it does not keep
  counting toward the old 96-bar/32-minute limit.
- Expect the training lane's balance trajectory to look different (and
  likely much less noisy) going forward, since trades will now
  actually get the time they were designed to need to reach TP.
- Manual `EXECUTION_MODE=paper` sessions are unaffected — same
  behavior as before this patch.
- Live trading is unaffected — this patch never touches
  `execution/execution_coordinator.py` or any order-placing path.

## Optional: tuning the timeout window

If 24 hours isn't the window you want, set in `.env`:
```
BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS=12
```
and restart. The actual bar count is recomputed automatically from
whatever `BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS` currently is — you
never need to hand-calculate a bar count yourself.

## Rollback

Revert this branch and restart — `PaperPosition.TIMEOUT_BARS` returns
to being the sole, unconditional default (96 bars at whatever cadence
each caller ticks at), exactly as before this patch.
