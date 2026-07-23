# PATCH NOTES — V16 Phase 3A: Strategy Plugin System

Branch: `feature/strategy-plugin-system`
Base: `main` (post Phase 2F merge, PR #8, 1512 passing)

## Summary

Adds a registry so `main.py`'s `ExecutionScheduler` bootstrap can
*select* which `signal_provider` implementation it uses (via
`config/settings.py`'s new `STRATEGY_NAME`) instead of the one
hardcoded `PortfolioSignalProvider(...)` construction Phase 2F left in
place. `execution/execution_orchestrator.py` (§23) already documented
this exact seam — `signal_provider: Callable[[str],
Optional[ExecutionSignal]]` — as something "whatever future phase
adapts per-symbol signal generation... plugs in as." This phase makes
that plug point selectable rather than hardcoded.

**The scope-defining work happened before writing any code.** The
original ask was six brand-new frameworks (Ensemble Decision Engine,
MCP Multi-Agent Framework, Strategy Plugin System, Quant Research
Pipeline, Research/Optimization Framework, AI Self-Improvement) in one
commit. Reading the actual codebase first — `agents/`,
`graph/agent_graph.py`, `commander/`, `decision/`,
`ranking/confidence_fusion.py`, `research/`, `ml/learning_mode.py` —
showed 4 of the 6 pillars already have substantial, production-wired
implementations under different names. Building new ones from scratch
would have created duplicate modules and touched live-wired code across
six unrelated areas in a single commit. Re-scoped to one phase at a
time; this phase is the first, chosen because Strategy Plugin System
was the only pillar with a genuine gap (no registry/interface existed
for `execution/strategy.py`'s single hardcoded strategy class) and the
lowest blast radius (touches one line of already-wired production code,
not six).

## New modules

| File | Purpose |
|---|---|
| `execution/strategy_registry.py` | `StrategyRegistry` — name → factory lookup for `signal_provider` implementations. Pre-registers `"portfolio_signal_provider"` (default, wraps the existing `PortfolioSignalProvider` unmodified) and `"smc_oi_regime"` (wraps `execution/strategy.py`'s `SMC_OI_Regime_Strategy` via the new `SMCOIRegimeStrategyAdapter`, which converts its bare tuple return into a full `ExecutionSignal`). |

## Changes to existing modules

| File | Change |
|---|---|
| `config/settings.py` | `+STRATEGY_NAME: str` (default `"portfolio_signal_provider"` — byte-for-byte the class Phase 2F hardcoded). |
| `main.py` | One construction swapped: `PortfolioSignalProvider(...)` → `build_strategy(settings.STRATEGY_NAME, ...)` with identical kwargs. No other line changed. |
| `docs/architecture.md` | +§25 (this phase). |
| `CLAUDE.md` | "Current Development Status" / "Current Priorities" updated — Portfolio Manager, Execution Scheduler, and this phase moved to Completed; the 6-pillar redesign recorded as the re-scoped roadmap, one phase at a time. |

Neither `execution/strategy.py`, `execution/portfolio_signal_provider.py`,
nor `execution/execution_orchestrator.py` were modified.

## Known limitation (documented, not hidden)

`"smc_oi_regime"` is registered but **not symbol-aware** —
`SMC_OI_Regime_Strategy.generate_signal()` reads one global
`data_provider` with no `symbol` parameter, so the adapter always
reflects the single globally-configured symbol regardless of what
`symbol` `ExecutionScheduler` asks it about. Do not set
`STRATEGY_NAME=smc_oi_regime` for the multi-symbol scheduler path. See
`execution/strategy_registry.py` module docstring and
`docs/architecture.md` §25 "Scope boundary".

## Testing

```
pytest tests/ -q   → 1533 passed, 0 failed  (1512 baseline + 21 new)
ruff check .        → clean
```

21 new tests in `tests/test_strategy_registry.py`: registry mechanics
against fresh `StrategyRegistry()` instances (register/get/build/list,
duplicate-registration and unknown-name error paths), both built-in
factories, and `SMCOIRegimeStrategyAdapter`'s tuple→`ExecutionSignal`
conversion against a fake underlying strategy.
