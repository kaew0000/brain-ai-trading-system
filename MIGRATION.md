# MIGRATION — V16 Phase 4C §49: Training Lane Restore-on-Restart

## Do you need to do anything?

**No.** This is purely additive and always-on (no new opt-in flag) —
the training lane already saved nothing across restarts before this,
so there's no prior behavior to preserve as a default; it now always
attempts to save/restore.

The new `training_lane_state` table is created automatically the next
time any connection opens against your database (`database/db.py`'s
existing schema-application step, idempotent — no separate migration
script needed, works the same for a fresh database and your existing
live one).

## What to expect after updating

- On the **first** boot after updating: nothing to restore yet — the
  lane starts exactly as it always has (fresh $100 account).
- On every boot **after that**: `logs/brain_bot.log` will show either
  `TrainingLaneRunner: restored prior state | balance=... open_positions=...`
  or nothing (if the lane hasn't run a single cycle yet on the new code,
  or a restore genuinely failed — logged as an ERROR if so, and the
  lane falls back to a fresh account exactly as before).
- The Train Monitor's background training panel will show
  `restored_from_prior_run: true/false` in its status data once this is
  wired into the dashboard display (not part of this phase — this phase
  only adds the field to the underlying `status()` dict; a future
  visibility pass could surface it in the UI the same way §47 surfaced
  the rest of this lane's status).

## Rollback

Revert `paper/paper_account.py`, `paper/paper_position.py`,
`paper/paper_execution.py`, `training_lane/training_lane_runner.py`,
`database/schema_v13.sql`; delete `training_lane/state_store.py`,
`tests/test_training_lane_state_store.py`, and this phase's additions to
`tests/test_training_lane_runner.py`. The `training_lane_state` table
itself is harmless to leave behind — nothing reads it once the code
reading it is gone.

## What this does not fix

See `PATCH_NOTES.md`'s "What this does not fix / does not do" for the
full list of deliberate scope boundaries.
