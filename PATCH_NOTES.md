# PATCH NOTES — Training-Lane Visibility + Boot-Enabled 24/7 Background Training

Branch: `feat/training-lane-visibility-and-boot-default`
Base: `main` @ `5eb52e0` (merge of PR #77, `fix/dashboard-boot-login`)

## Root cause

Reported symptom: "Train Monitor ขึ้น block หมด" (Train Monitor shows
everything blocked). Traced against a real run.bat production log
provided alongside the request:

```
13:16:57 [WARNING] risk.risk_engine: TRADING DISABLED TODAY | Consecutive losses: 3/3
13:17:53 [INFO] execution.execution_scheduler: ExecutionScheduler: decision blocked (Trading disabled for today)
```

Train Monitor's "Scanner Decision Log" panel was correctly reporting
this — every row shows `BLOCKED` because it renders
`PortfolioHistoryEntry.blocked`, sourced from the *live* scanner/CEO
decision cycle, which the real RiskEngine's circuit breaker was
legitimately halting for the day. Not a display bug.

The actual gap: `training_lane/training_lane_runner.py` (Phase 4C
Track C, merged PR #76) already implements everything the request
described — a fully isolated $100 paper account that runs
independent of the live circuit breaker/lifecycle state, resets
immediately (no cooldown, no wait) when it busts, and captures the
bust event as a labelled training row. But
`BACKGROUND_PAPER_TRAINING_ENABLED` defaulted to `False`, and the
provided boot log has no `TrainingLaneRunner started` line — the lane
was never enabled. Train Monitor also had no panel surfacing Track
C's own state at all, so even once enabled there was nothing on
screen distinguishing "training is fine, only the live scanner is
blocked" from "everything is broken."

Confirmed via direct inspection (not assumed) before writing any
code:
- `config/settings.py:455` — flag default was `False`.
- `main.py:670` — `if settings.BACKGROUND_PAPER_TRAINING_ENABLED:` guard,
  never true with the shipped default.
- `main.py` — `training_lane_runner` was registered in `components`
  for graceful shutdown only; never passed into `_start_api_server()`,
  so the API layer had zero visibility into it even when running.

## What changed

### `config/settings.py`
`BACKGROUND_PAPER_TRAINING_ENABLED` default flipped `False → True` —
literal reading of "เทรน 24/7 เมื่อเปิดระบบ" (train 24/7 whenever the
system opens): training must start automatically on boot, not require
a manual `.env` edit first. This is the one explicit default-behavior
change in this phase (see MIGRATION.md). The lane it enables is
provably isolated (own `PaperAccount`, own `PaperExecutionEngine`, no
import capable of placing a real order — mechanically verified by
`tests/test_training_lane_runner.py::TestNoRealOrderPath`, unchanged
by this phase), so flipping the default carries no live-money risk;
it only adds one extra background thread + local DB writes to a
fresh boot. Anyone who doesn't want that can still set
`BACKGROUND_PAPER_TRAINING_ENABLED=false` in `.env`.

### `training_lane/training_lane_runner.py`
Added `TrainingLaneRunner.status()` — a read-only plain-dict snapshot
(`enabled`, `is_running`, `symbol`, `starting_balance`, `balance`,
`bust_count`, `closed_trade_count`, `open_position`,
`last_closed_trade`, `poll_interval_seconds`). Reads only
already-lock-protected properties (`PaperAccount.balance`,
`PaperExecutionEngine.open_positions`/`.closed_trades` each take
their own internal lock) and returns `PaperPosition.to_dict()` /
`ClosedTrade.to_dict()` plain dicts — never a reference to the live
mutable objects, so a caller can't mutate training state through the
status surface. No behavior change to the existing cycle/bust logic.

### `main.py`
`_start_api_server()` gained a `training_lane_runner=None` parameter,
injected via the existing `set_state()` mechanism (same pattern as
`paper_engine`/`reconciliation_engine` above it) and wired at the one
call site from `components.get("training_lane_runner")`. Purely
additive — every existing parameter/call site untouched.

### `api/app.py`
New `GET /api/training-lane/status`. Same "always 200, `enabled` flag
tells the story" contract as the existing `/api/paper` and
`/api/paper/metrics` routes right above it (off/not-wired is a normal
runtime state, not a 404/503). Passes `TrainingLaneRunner.status()`
straight through with no reshaping.

### Dashboard (`dashboard_src/`)
- `types/api.ts` — `TrainingLaneStatus`, `TrainingLanePosition`,
  `TrainingLaneClosedTrade`, field names matching
  `PaperPosition.to_dict()` / `ClosedTrade.to_dict()` exactly.
- `lib/api.ts` — `trainingLaneStatus()`, same one-line `get()` wrapper
  style as its neighbors.
- `pages/TrainMonitor.tsx` — new "Background Training Lane (Track C)"
  panel, polled locally every 20s (matching
  `BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS`'s own default), placed
  as the first panel below the KPI row so it's the first thing visible
  on the tab. Shows running/stopped, balance vs. starting balance
  (color-coded), bust count, closed-trade count, current open
  position, and the most recent closed trade — with an in-panel Thai
  note (matching the existing note style already used lower on this
  same page) making explicit that this account is completely separate
  from the real account and keeps training even while the real
  account's circuit breaker is tripped. This directly answers "is
  training still happening" regardless of live circuit-breaker state
  — the actual gap behind the reported symptom.

No existing export touched in any file. No change to `risk/`,
`execution/execution_coordinator.py`, or any live-order code path.

## Testing

**Track A** — `pytest tests/`: 2823 passed, 45 deselected (unrelated
markers), 3 pre-existing failures in `tests/test_dashboard_serving.py`
confirmed identical on unmodified `main` (they require a built
`dashboard_src/dist/`, environmental, not caused by this phase — see
below). `ruff check . --exclude dashboard_src --exclude dashboard`:
clean. `vulture . --exclude dashboard_src,dashboard,tests
--min-confidence 80`: clean. `python3 -c "import main"`: clean.

18 tests in `tests/test_training_lane_runner.py` (up from 14): new
`TestStatus` class (shape when flat, reflects an open position and a
closed trade, reflects bust count + reset balance, never leaks
mutable engine references) plus `TestBootFlag` rewritten for the new
default — `test_flag_on_by_default`, a new
`test_flag_still_respects_env_override_off` (confirms the escape
hatch), and `test_main_guard_constructs_runner_only_when_flag_true`
(replaces the old flag-off-only guard test; now exercises both
directions of the guard, which the previous version never actually
did — see MIGRATION.md).

2 new tests in `tests/test_api.py::TestTrainingLane`, mirroring
`TestPaper`'s existing pattern exactly (disabled-when-not-wired,
enabled-passes-through-unchanged).

**Track B** — `npx tsc --noEmit`: clean. `npx vitest run`: 101 passed
(101), no new test files needed — the new panel is presentational
(same convention as every other page-local poll panel in this file,
none of which are unit-tested individually) and `trainingLaneStatus()`
is a trivial one-line GET wrapper (same convention as `mlModels()`/
`portfolioHistory()`, neither of which are unit-tested either).
`npm run build`: clean production build (`TrainMonitor-*.js` grew from
its previous size to 14.76 kB / 4.11 kB gzipped).

### Pre-existing failures (not this phase's)

`tests/test_dashboard_serving.py` — 3 tests require a built
`dashboard_src/dist/index.html` to exist on disk; this sandbox never
ran `npm run build` before this phase started. Confirmed via `git
stash` + re-run against unmodified `main`: identical 3 failures,
0 changes. Not touched by this phase.

## Known follow-up (not done here, out of scope for this phase)

- `docs/CHANGELOG.md`'s `[Unreleased]` section is overwritten
  per-phase rather than accumulated (pre-existing convention, flagged
  separately as its own backlog item — "CHANGELOG.md cleanup pass").
  Followed the existing convention as-is here rather than silently
  changing it mid-phase.
- No panel currently surfaces *why* the live circuit breaker tripped
  beyond the existing `block_reason` tooltip already on the Scanner
  Decision Log row — out of scope; this phase's ask was specifically
  about the training lane being independently visible, not about
  redesigning the live-blocked view.
