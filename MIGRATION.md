# MIGRATION — Training-Lane Visibility + Boot-Enabled 24/7 Background Training

## Do you need to do anything?

**Only if you want the old opt-in-only behavior back.** This phase
contains one deliberate default-behavior change, made on explicit
request — everything else is purely additive.

## The one behavior change: `BACKGROUND_PAPER_TRAINING_ENABLED` now defaults to `true`

Before this phase, importing a bundle and restarting the bot never
started the Track C background paper-training lane unless you'd
already set `BACKGROUND_PAPER_TRAINING_ENABLED=true` in `.env`. After
this phase, a fresh boot with no `.env` change will now:

- Start `training_lane/training_lane_runner.py::TrainingLaneRunner` on
  its own daemon thread, on a $100 isolated paper account
  (`BACKGROUND_TRAINING_STARTING_BALANCE`, unchanged default), polling
  every 20s (`BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS`, unchanged
  default).
- That thread reads mark prices (read-only, reuses the existing data
  provider — no new network credentials or exchange permissions) and
  writes to your local training database via the existing
  `FeatureStore`/`DatasetBuilder` pipeline, tagged
  `execution_lane="PAPER"` (`TRAINING_LANE` constant, unchanged).

**What it will never do**, unchanged from before this phase and
independently re-verified by `tests/test_training_lane_runner.py::
TestNoRealOrderPath` (still passing): place a real order, touch your
real balance, or import anything capable of reaching
`execution/execution_coordinator.py` or a Binance order client. It
also runs regardless of your real account's lifecycle
state/circuit-breaker status — that's the whole point (see
PATCH_NOTES.md's root-cause section) — so it will keep running even
while your real account shows `TRADING DISABLED TODAY`.

### If you don't want this

Add to `.env`:

```
BACKGROUND_PAPER_TRAINING_ENABLED=false
```

This restores the exact previous behavior — verified by
`tests/test_training_lane_runner.py::TestBootFlag::
test_flag_still_respects_env_override_off`.

## Everything else: purely additive, nothing to do

- `GET /api/training-lane/status` is a new, additive endpoint. No
  existing endpoint's response shape changed.
- The new "Background Training Lane" panel on the Train Monitor tab
  only appears once the frontend is rebuilt (`npm run build` in
  `dashboard_src/`, same as every dashboard-touching phase) — until
  then the tab renders exactly as before, just without the new panel.
- If you're running with `BACKGROUND_PAPER_TRAINING_ENABLED=false`
  (either because you set it explicitly, or if `main.py` failed to
  start the runner for any reason), the new panel will render a plain
  "not running" state instead of an error — same posture as every
  other optional-subsystem panel already in this dashboard.

## Note on the test that changed behavior, not just names

`tests/test_training_lane_runner.py::TestBootFlag::
test_main_does_not_construct_runner_when_flag_off` (old name) only
ever exercised the flag-*off* branch of the boot guard, because the
old default was `False` and the test's own `if
settings_mod.settings.BACKGROUND_PAPER_TRAINING_ENABLED:` conditional
never evaluated its `True` branch. Its replacement,
`test_main_guard_constructs_runner_only_when_flag_true`, now exercises
*both* directions explicitly via a local `_boot_guard(flag_enabled)`
helper — worth knowing if you're diffing test behavior, not just test
names, since this closes a real (if low-stakes) pre-existing gap in
what that test actually proved.
