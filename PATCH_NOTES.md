# PATCH NOTES — Enforce scheduler_safe Strategy Selection (V16 §65)

Branch: `fix/enforce-scheduler-safe-strategy`
Base: `main` @ `0b4dc88` (merge of PR #100, sl-distance-zero fix)

## Context

Closes the "HMM cross-symbol contamination" item from this week's
broader audit — re-investigated and found to be less severe than
originally flagged: `execution/portfolio_signal_provider.py` (the
default `STRATEGY_NAME`) already correctly passes `symbol=` into
`RegimeEngine.classify()` (added in Phase 4B Step 3A), so the default
configuration was never actually contaminated. The real, narrower gap:
`execution/strategy_registry.py`'s legacy `"smc_oi_regime"` strategy
— explicitly documented in its own module docstring, class docstring,
and registration description as "NOT symbol-aware... Do not select
for ExecutionScheduler" — had **no code enforcing that**. Only
documentation stood between a `STRATEGY_NAME=smc_oi_regime` +
`SCHEDULER_ENABLED=true` configuration and silent cross-symbol
contamination.

## Root cause

`execution/strategy.py::SMC_OI_Regime_Strategy.generate_signal()` has
no `symbol` parameter anywhere in its interface — it reads one global
`data_provider.get_all_market_data()`. Its registry adapter
(`SMCOIRegimeStrategyAdapter`) accepts a `symbol` argument only to
satisfy the `SignalProvider` callable shape, and ignores it entirely
(confirmed, and already documented, by
`execution/strategy_registry.py`'s own docstrings). `main.py`'s
`ExecutionScheduler` startup block called `build_strategy(settings.
STRATEGY_NAME, ...)` with no check of whether the selected strategy
was actually safe for that path — the "not safe to select" warning
existed only in prose.

## Fix

`execution/strategy_registry.py`:
- `StrategySpec` gained `scheduler_safe: bool = True`.
- `register()` / `register_strategy()` gained a matching
  `scheduler_safe` parameter (default `True` — no behavior change for
  any strategy that doesn't explicitly opt out).
- `"smc_oi_regime"` is now registered with `scheduler_safe=False`.
- New `StrategyRegistry.is_scheduler_safe(name)` / module-level
  `is_scheduler_safe(name)` — fails closed (an unregistered name
  returns `False`, not `True`).
- `list_strategies()` now includes `scheduler_safe` per entry.

`main.py`: the `ExecutionScheduler` startup block now checks
`is_scheduler_safe(settings.STRATEGY_NAME)` alongside its existing
`market_scanner is None` precondition check, using the exact same
guarded, non-fatal pattern (`logger.error(...)`, scheduler simply
doesn't start) — not a hard crash, consistent with every other
scheduler-startup precondition in this block.

## Tests

`tests/test_strategy_registry.py` — new `TestSchedulerSafeFlag` (6
tests): defaults to `True` for a freshly registered strategy, can be
registered as unsafe, an unregistered name is not scheduler-safe
(fail-closed), the module-level helper matches the registry method,
`list_strategies()` exposes the field, and the two built-in
multi-symbol-safe strategies (`portfolio_signal_provider`,
`smc_oi_regime_multi`) are correctly `True` while `smc_oi_regime` is
correctly `False`.

`main.py`'s own enforcement (the `elif` branch itself) is not
separately unit-tested — same reasoning as §60's precedent:
`main()` is a large, side-effecting entry point not designed for unit
testing, and the branch is a thin, self-evidently-correct call into
the now-tested `is_scheduler_safe()`. Verified by direct code review.

All 117 pre-existing tests across every file touching the strategy
registry (`test_strategy_registry.py`, `test_smc_oi_regime_multi.py`,
`test_ceo_multi_symbol_agent_attribution.py`,
`test_training_lane_runner.py`) pass unchanged after adding the
`scheduler_safe` kwarg (defaults preserve every existing call site's
behavior).

Full suite: `pytest tests/` → **3112 passed** (up from 3106), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on both changed source files (one
pre-existing, unrelated finding — `main.py`'s signal-handler `frame`
parameter, confirmed identical on unmodified `main` in every prior
phase this week that touched this file).
`python -c "import main"` → succeeds.

## Files changed

`execution/strategy_registry.py`, `main.py`,
`tests/test_strategy_registry.py`, `PATCH_NOTES.md`, `MIGRATION.md`,
`CHANGELOG.md`, `docs/architecture.md` (§65).
