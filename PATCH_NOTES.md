# PATCH NOTES — Fix: Training Lane Position TIMEOUT Firing at ~32 Minutes Instead of ~24 Hours

Branch: `fix/training-lane-timeout-bars-poll-interval`
Base: `main` @ `d247f80` (merge of PR #83, ML Extensions Integration Layer)

## Reported symptom

Operator observed the Background Training Lane (Track C,
`localhost:8000/train`) bleeding paper balance every day for 3 days:
$100 → $90.98 over 19 closed trades in the session shown, with the
last closed trade `close_reason=TIMEOUT`, `result=LOSS`. Live trading
was separately unavailable (deposit/start-bot blocked), so this lane
was the operator's only real signal into whether the decision logic
works at all — and it looked like it was losing on its own, not just
idle.

## Root cause (confirmed by reading the code, not assumed)

`paper/paper_position.py`:
```python
TIMEOUT_BARS = 96      # ~24 h at M15 — auto-close if no SL/TP hit
...
self._bars_open += 1
...
if self._bars_open >= self.TIMEOUT_BARS:
    return self._close(self.mark_price, "TIMEOUT")
```

`_bars_open` increments once per `update_mark()` call. The comment's
"~24h at M15" is only true if `update_mark()` fires once per real M15
candle close. It doesn't — `PaperExecutionEngine.tick()` calls
`update_mark()` on every open position once per
`TrainingLaneRunner._cycle()`, and `_cycle()` runs once every
`settings.BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS` (**20 seconds by
default**, confirmed in `config/settings.py`).

`96 bars × 20s/bar = 1,920s ≈ 32 minutes` — not 24 hours.

Every position opened by this lane was therefore force-closed at
whatever the mark price happened to be after ~32 minutes, almost
always well before the strategy's SL/TP levels (sized for realistic
M15/H1 movement) had a real chance to resolve either way. TP rarely
had time to be hit; SL could still be hit normally; everything else
closed near-flat-to-negative once the 0.04%-per-side taker fee is
applied twice per trade. That's a mechanical, structural drag on the
account independent of whether the underlying signal has any edge —
consistent with the model's own reported backtest stats (37.5% win
rate, PF 3.32) not looking obviously broken while the live paper
balance still bled down daily.

## Fix

Calibrate the timeout to each caller's *actual* tick cadence instead
of hardcoding an assumption about M15 candles:

- **`paper/paper_position.py`** — `PaperPosition.__init__` gains an
  optional `timeout_bars: int | None = None` param. `TIMEOUT_BARS=96`
  stays as the class-level *default*, used only when a caller omits
  the param — so every existing caller that constructs `PaperPosition`
  directly (`execution/execution_factory.py`'s manual
  `EXECUTION_MODE=paper` wiring, and every pre-existing test) is
  byte-for-byte unaffected. `to_state_dict()`/`from_state_dict()` now
  carry `timeout_bars` too, with a `default_timeout_bars` fallback for
  state saved before this fix.
- **`paper/paper_execution.py`** — `PaperExecutionEngine.__init__`
  gains an optional `timeout_bars` param, passed through on every
  `execute()` call and on `from_state_dict()` restore.
- **`config/settings.py`** — new
  `BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS: float = 24.0`. Rule 16
  (never hardcode values) — the intended real-world timeout is now a
  config knob, not a magic number recomputed ad hoc.
- **`training_lane/training_lane_runner.py`** — `TrainingLaneRunner.__init__`
  computes
  `self._timeout_bars = max(1, int(TIMEOUT_HOURS * 3600 / poll_interval_seconds))`
  once, from its own actual `poll_interval_seconds`, and passes it to
  every engine it builds (`_new_engine()`) or restores
  (`_restore_state()`). If `BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS`
  is ever changed later, the real-world timeout stays correct
  automatically — no second place to remember to update.

## Explicitly out of scope

- Manual `EXECUTION_MODE=paper` sessions (`execution/execution_factory.py`)
  — never reported as broken, left on the original 96-bar/M15 default.
  Only Track C's always-on background lane (whose poll cadence is known
  and configurable) was recalibrated.
- Live trading (`execution/execution_coordinator.py`) — never imports
  or touches `PaperPosition`; no real-money code path is affected.
- The separate "can't deposit / can't start bot from live" issue the
  operator also raised — different subsystem, not investigated in this
  patch; flagged back to the operator as a follow-up.

## Tests

New: `tests/test_training_lane_runner.py::TestTimeoutBarsCalibratedToPollInterval`
(3 tests):
1. `_timeout_bars` is correctly derived from
   `BACKGROUND_TRAINING_POSITION_TIMEOUT_HOURS` and the runner's actual
   `poll_interval_seconds`.
2. A position that would have died via `TIMEOUT` after the old
   hardcoded 96 ticks now survives them at a flat price (direct
   reproduction of the bug, proven fixed).
3. The calibrated value — not the raw 96 default — survives a restart
   via `TrainingLaneRunner._restore_state()`.

Results:
- `tests/test_phase4c.py`, `tests/test_audit_fixes.py`,
  `tests/test_training_lane_runner.py`: baseline 227 passed before any
  change; 227 passed + 3 new = 230 passed after (existing tests
  required zero modification — confirms backward compatibility held).
- Full backend suite: **3006 passed, 4 skipped**. 3 failures in
  `tests/test_dashboard_serving.py` are pre-existing on unmodified
  `main` (missing `dashboard/dist/` build artifact in a fresh clone —
  audit finding predating this phase, reproduced independently on
  `main` before branching) — unrelated to this fix.
- World suite (`world/tests/`, `tests/test_world_*.py`,
  `tests/test_main_world_runtime_wiring.py`): **72 passed**.
- `ruff check` and `vulture --min-confidence 80`: clean on every
  changed file.
- `ast.parse()` + fresh import of every changed module: OK.
