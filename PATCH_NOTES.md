# PATCH NOTES — Close Out V16 BUG-LIVE-RISK-06: Scheduler-Path Gate 0 + Restart Persistence

Branch: `fix/risk-override-scheduler-gate-and-restart-persistence`
Base: `main` @ `a1fe1c2` (merge of PR #92, report()/peek_can_trade() fix)

This phase closes both items flagged as "known follow-up, not fixed"
in PR #92's PATCH_NOTES:

1. `portfolio/capital_manager.py`'s Gate 0 still calling the
   consuming `can_trade()` (dormant today, `SCHEDULER_ENABLED=False`,
   but wrong once the multi-symbol scheduler path is enabled).
2. The sibling branch `fix/risk-override-persists-across-restart`
   (commit `61cea14`, unmerged, no PR opened) that would otherwise
   conflict with PR #92 on merge.

## Part 1 — Scheduler-path Gate 0 (root cause)

`portfolio/capital_manager.py:157` (`CapitalManager.decide()`'s
"Gate 0", `# Never allocate if RiskEngine already blocks trading —
checked before anything else, unconditionally`) called
`risk_engine.can_trade(balance)` — the consuming gate — as a
pre-check, before any candidate had been ranked, filtered, or
allocated capital.

Traced the full scheduler flow (`execution/execution_scheduler.py` →
`portfolio/portfolio_manager.py::decide()` →
`portfolio/capital_manager.py::decide()` →
`execution/execution_orchestrator.py::execute()`) to confirm: after
Gate 0 passes, `CapitalManager.decide()` runs per-candidate
eligibility gates (`portfolio_full`, `already_held`,
`liquidity_below_minimum`, `spread_below_minimum`,
`coverage_below_minimum`, `correlation_hard_reject`,
`risk_budget_exhausted`, `no_capital_remaining`), and
`PortfolioManager.decide()` layers on further cooldown and
sector-exposure filtering on top of that. Any of these can reduce the
final `selected`/`replacements` lists to empty. `execute()` itself
never touches `RiskEngine` at all. So an armed one-shot override could
be consumed by Gate 0 and then never actually used for a real order —
the same failure mode as the just-fixed `report()` bug, one layer
deeper.

### Fix

- `portfolio/capital_manager.py` — Gate 0 now calls
  `risk_engine.peek_can_trade(balance)` (read-only, added in PR #92).
  Manual holds and genuine account-level blocks (daily loss latch,
  consecutive-loss latch with no override armed) still short-circuit
  the whole cycle exactly as before — only the "consume an armed
  override just to pre-check" behavior changes.
- `execution/execution_scheduler.py::run_once()` — added the real,
  consuming `risk_engine.can_trade(balance)` call, placed immediately
  before `ExecutionOrchestrator.execute()`, and only reached when
  `decision.selected` or `decision.replacements` is non-empty (i.e.
  there is definitely something about to be executed this cycle).
  Mirrors `main.py`'s own gate placement for the legacy single-symbol
  loop — same principle (peek early, consume late), same relative
  position (immediately before the code that actually places orders).
- `portfolio/portfolio_models.py` — one docstring comment updated for
  accuracy (`PortfolioDecision.blocked` now documents
  `peek_can_trade()`, not `can_trade()`).

**Known, documented divergence (not fixed this phase):** if
`CapitalManager.decide()` selects more than one allocation in the same
cycle, one consumed override now lets the entire batch through, not
just one probe trade — because the override is single-symbol-loop
"one `can_trade()` call = one trade" by design, and the scheduler path
can produce multiple simultaneous orders per cycle. Flagged in
`docs/architecture.md` §57 and in `execution_scheduler.py`'s own
comment at the new call site, not silently redesigned. Dormant either
way today (`SCHEDULER_ENABLED=False` default).

## Part 2 — Restart persistence (BUG-LIVE-RISK-04)

Integrated `fix/risk-override-persists-across-restart` (commit
`61cea14`) on top of PR #92's `_evaluate(mutate=bool)` refactor,
faithfully reproducing its design (verified by diffing that commit
against its own base `c0d12a0` in isolation, not against current
`main`, to see its changes cleanly):

- `journal/journal_v2.py` — new `risk_engine_state` table
  (lazily created, `CREATE TABLE IF NOT EXISTS`) plus
  `save_risk_override()` / `get_risk_override()` /
  `clear_risk_override()`.
- `risk/risk_engine.py::__init__` — restores a persisted override on
  construction, guarded by `isinstance(restored, str)` specifically
  because most existing `RiskEngine` tests construct it with a bare
  `MagicMock()` journal, and `getattr(mock, "get_risk_override", None)`
  is truthy on an unconfigured mock (returns another MagicMock, not
  `None`) — the `str` check is what stops every one of those tests
  from silently getting a fake override armed on construction.
- `override_next_trade_despite_streak()` / `clear_consecutive_loss_
  override()` — now write-through / clear the persisted copy.
- Both consumption points inside `_evaluate()`'s `if mutate:` branches
  — now also call `_clear_persisted_override()`. Persistence is
  cleared only on real consumption (`mutate=True`), never by
  `peek_can_trade()`, consistent with PR #92's mutate/peek split.
- `tests/test_risk_override_persistence.py` — brought in unchanged
  (11 tests): journal round-trip, restore-on-construction, end-to-end
  restore-then-consume, and the MagicMock false-positive guard.

## Tests

New/updated:
- `tests/test_execution_scheduler.py` — `FakeRiskEngine` added
  (previous `risk_engine=object()` default silently worked only
  because nothing called it directly before this phase; now
  `run_once()` does). 4 new tests in `TestRealRiskGate`: called
  exactly once on a successful cycle, blocks execution even when
  `decide()` itself wasn't blocked, NOT called when nothing was
  selected/replaced, NOT called when `decide()` was already blocked.
- `tests/test_capital_manager.py`, `tests/test_portfolio_manager.py`
  — `make_risk_engine(blocked=True)` now mocks both `can_trade` and
  `peek_can_trade` identically (Gate 0 calls the latter now).
- `tests/test_risk_override_persistence.py` — new, 11 tests (from the
  sibling branch, unmodified).

Full suite: `pytest tests/` → **3023 passed, 4 skipped, 45
deselected**. Same 3 pre-existing `tests/test_dashboard_serving.py`
failures as PR #91/#92 (missing frontend build artifact) — unrelated,
confirmed unaffected by this diff.

`ruff check .` → all checks passed (repo-wide). `vulture` on every
changed source file, `--min-confidence 80` → no dead code.
`python -c "import main"` → succeeds.

## Files changed

`risk/risk_engine.py`, `journal/journal_v2.py`,
`portfolio/capital_manager.py`, `portfolio/portfolio_models.py`,
`execution/execution_scheduler.py`, `tests/test_audit_fixes.py`
(unchanged from PR #92, carried forward), `tests/test_capital_manager.py`,
`tests/test_portfolio_manager.py`, `tests/test_execution_scheduler.py`,
`tests/test_risk_override_persistence.py` (new), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`, `docs/architecture.md` (§57).

## Superseded branch

This branch supersedes `fix/risk-override-persists-across-restart`
(`61cea14`) — its intent is fully incorporated here, rebased onto
PR #92's refactor. Recommend closing that branch/PR without merging
once this one lands, rather than merging both (they touch identical
lines and would conflict).
