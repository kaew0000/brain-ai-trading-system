# PATCH NOTES — Fix: report() Silently Consuming the One-Shot Risk Override (V16 BUG-LIVE-RISK-06)

Branch: `fix/risk-override-consumption-race`
Base: `main` @ `623161d` (merge of PR #91, HFT-1 order-book pu-authoritative sequencing)

## Reported symptom (root cause, not yet observed as a live incident)

Discovered during an architecture review, not from a reported live
incident: `RiskEngine.report()` — the method used purely for
status/dashboard/telemetry — called `self.can_trade(balance)`
internally. `can_trade()` has a documented, intentional side effect:
it consumes an armed one-shot consecutive-loss override
(`override_next_trade_despite_streak()`) so the override behaves as a
genuine "let exactly one trade through" lever, not a standing disable.

`report()` is not a trade decision. It is called:
- every single trading cycle by `RiskManagerAgent`
  (`agents/risk_manager.py`) purely to build dashboard narrative and
  HALT/ELEVATED/CAUTION classification, and
- on-demand by Commander's `_build_commander_context()`
  (`api/app.py`) every time an operator asks "show risk" via the
  dashboard chat.

Before this fix, either of those routine, read-only calls could
silently consume an operator's armed override — arming it via the
dashboard and then simply checking status before the real trade cycle
ran would burn it for nothing, with no trade ever executed and no
visible error.

## Root cause (confirmed by reading the code, not assumed)

`risk/risk_engine.py::report()`:
```python
ok, reason = self.can_trade(balance)
```
`can_trade()`'s consecutive-loss branch:
```python
if self._consecutive_loss_override_reason is not None:
    self._consecutive_loss_override_reason = None   # one-shot: consume now
    ...
    return True, ""
```
`report()` had no way to read "would this pass" without also
triggering "and consume the one-shot lever if it does." The two
concerns — computing the verdict, and spending a one-shot resource —
were fused into a single method with no way to separate them.

## Fix

`risk/risk_engine.py`:
- Extracted the full gate logic into a private
  `_evaluate(balance, *, mutate: bool)`. All existing behavior is
  unchanged when `mutate=True`.
- `can_trade(balance)` now calls `_evaluate(balance, mutate=True)` —
  byte-for-byte the same observable behavior as before (latches
  `_disabled_today`, consumes an armed override). This is still the
  ONLY method that should be called immediately before actually
  placing a real trade (`main.py`'s per-cycle gate,
  `portfolio/capital_manager.py`'s Gate 0).
- New `peek_can_trade(balance)` calls `_evaluate(balance, mutate=False)`
  — returns the identical `(ok, reason)` verdict, but never mutates
  state: an armed override stays armed, and a fresh breach is reported
  without latching `_disabled_today`.
- `report()` now calls `self.peek_can_trade(balance)` instead of
  `self.can_trade(balance)`. This is the only call-site change needed
  — every existing caller of `report()` (`agents/risk_manager.py`,
  `api/app.py`'s Commander context, `main.py::daily_report()`) is
  fixed automatically, with no changes needed at those call sites.

No public method signature changed. `can_trade()`'s behavior is
byte-for-byte unchanged for its two real call sites (`main.py`,
`portfolio/capital_manager.py`).

## Tests

`tests/test_audit_fixes.py::TestRiskEngine` (all against a mocked
journal, no live API calls):
- `test_report_never_consumes_the_override` — rewritten from
  `test_report_shows_override_armed_before_consumption`, which
  previously *asserted the bug as correct behavior* (a second
  `report()` call was expected to show the override cleared). Now
  asserts the override survives any number of `report()` calls and is
  only spent by an actual `can_trade()` call.
- `test_peek_can_trade_never_mutates_state` — new
- `test_peek_can_trade_matches_can_trade_when_no_override_armed` — new
  (peek and the real gate must agree exactly when nothing is armed)
- `test_peek_can_trade_does_not_bypass_manual_hold` — new
- `test_peek_can_trade_does_not_clear_the_sticky_latch` — new (mirrors
  the existing sticky-latch override test, for the peek path)

Full suite: `pytest tests/` → **3007 passed, 4 skipped, 45 deselected**.
3 failures in `tests/test_dashboard_serving.py` are pre-existing and
unrelated — confirmed by running the same file against unmodified
`main` (identical 3 failures): they require a built
`dashboard_src/dist/index.html` (Track B frontend build), which does
not exist in this sandbox checkout.

`ruff check .` → all checks passed. `vulture risk/risk_engine.py
--min-confidence 80` → no dead code. `python -c "import main"` →
succeeds.

## Known follow-up (not this phase — flagged, not fixed)

**`portfolio/capital_manager.py:145`** (`CapitalManager.decide()`'s
"Gate 0") also calls `risk_engine.can_trade(balance)` — once per
portfolio-evaluation cycle, before any candidate is selected. This is
currently **dormant**: `SCHEDULER_ENABLED=False` by default, so this
code path does not run in the current live single-symbol deployment.
It will become live once the multi-symbol/scheduler path is turned on
(relevant to the planned BTCUSDT → lower-minimum-notional symbol
migration). Simply swapping this call to `peek_can_trade()` would be
**wrong**: nothing else in the scheduler/execution-orchestrator flow
currently calls the mutating `can_trade()`, so an armed override would
never actually get consumed and would keep bypassing the block on
every cycle indefinitely — the opposite of "one-shot." Fixing this
correctly requires first tracing `execution/execution_scheduler.py`
and `execution/execution_orchestrator.py` to find (or add) the actual
point where a selected candidate becomes a real order, and moving the
`can_trade()`/consumption call there. Not inspected deeply enough this
phase to patch safely — flagged per this project's "stop and report at
scope boundaries" convention rather than guessed at.

**Sibling branch collision:** `fix/risk-override-persists-across-restart`
(commit `61cea14`, pushed but not yet merged, no PR opened) also
modifies `risk/risk_engine.py` — same class, overlapping lines
(`__init__`, `override_next_trade_despite_streak()`,
`clear_consecutive_loss_override()`, and the same two
override-consumption call sites `can_trade()` now guards with
`mutate`). It fixes a different, real bug (override doesn't survive a
bot restart) but **will produce a textual merge conflict** with this
branch regardless of merge order. Recommend reviewing/merging one
branch fully, then rebasing the other on top by hand rather than
merging both independently.
