"""
execution/strategy_registry.py — V16 Phase 3A: Strategy Plugin System

Formalises the plug point execution/execution_orchestrator.py already
documents (its own module docstring's "Signal boundary" section):
ExecutionOrchestrator takes a `signal_provider: Callable[[str],
Optional[ExecutionSignal]]` constructor dependency and "does not know or
care how it is implemented." Today main.py hardcodes exactly one
implementation (PortfolioSignalProvider) at that call site. This module
does not replace that implementation — PortfolioSignalProvider,
SMC_OI_Regime_Strategy, ExecutionOrchestrator, and main.py's trading
loop are all completely unmodified by this phase — it adds a registry
so a `signal_provider` can be *selected* (via config/settings.py's new
STRATEGY_NAME) instead of hardcoded, and so future strategies can be
added without editing main.py's wiring block again.

Built-in strategies registered below
-------------------------------------
"portfolio_signal_provider" (default — byte-for-byte the same class
main.py constructed directly before this phase):
    Wraps execution/portfolio_signal_provider.py's PortfolioSignalProvider.
    Symbol-aware (accepts an arbitrary symbol per call) — this is the
    only strategy safe to select for ExecutionScheduler's multi-symbol
    path today.

"smc_oi_regime":
    Wraps execution/strategy.py's SMC_OI_Regime_Strategy via
    SMCOIRegimeStrategyAdapter below. Registered for plugin-system
    completeness and any future single-symbol standalone use — NOT
    safe to select for ExecutionScheduler. SMC_OI_Regime_Strategy reads
    one global data_provider with no symbol parameter (confirmed by
    reading execution/strategy.py directly, and independently noted by
    execution_orchestrator.py's own "Signal boundary" docstring), so
    this adapter's generate_signal() always reflects the single
    globally-configured symbol regardless of what `symbol` string is
    passed to it. Documented honestly rather than silently papered
    over — matches this project's existing convention (see
    commander/control_state.py's "Honesty about paper_mode_forced").

Adding a new strategy
----------------------
Call register_strategy(name, factory, description=...) with a
factory(**kwargs) -> SignalProvider callable. main.py's bootstrap
passes a fixed superset of kwargs (data_provider, regime_engine,
smc_engine, volume_engine, context_builder, confidence_engine) to
whichever factory config/settings.py's STRATEGY_NAME selects; a factory
that needs a kwarg not in that superset (as "smc_oi_regime"'s
decision_engine currently is not) should raise a clear ValueError
listing what's missing rather than guessing or crashing obscurely —
main.py's existing SCHEDULER_ENABLED try/except (unchanged by this
phase) already catches and logs exactly that, non-fatally, the same
way it already handles any other ExecutionScheduler startup failure.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

from execution.execution_orchestrator import ExecutionSignal
from utils.logger import get_logger

logger = get_logger(__name__)

# Matches execution/execution_orchestrator.py's own
# SignalProvider = Callable[[str], Optional[ExecutionSignal]] exactly —
# a factory returns anything satisfying that contract.
StrategyFactory = Callable[..., Callable[[str], Optional[ExecutionSignal]]]


@dataclass(frozen=True)
class StrategySpec:
    name: str
    factory: StrategyFactory
    description: str = ""


class StrategyRegistry:
    """Name -> factory lookup for signal_provider implementations.

    Duplicate registration under an existing name raises by default
    (override=True to replace deliberately) — a silent overwrite would
    let a later import quietly shadow an earlier strategy with no
    signal anything changed, which is exactly the class of bug this
    project's own §24 write-up flags import-shadowing bugs for.
    """

    def __init__(self) -> None:
        self._strategies: Dict[str, StrategySpec] = {}

    def register(
        self,
        name: str,
        factory: StrategyFactory,
        description: str = "",
        override: bool = False,
    ) -> None:
        if not name or not isinstance(name, str):
            raise ValueError("Strategy name must be a non-empty string")
        if name in self._strategies and not override:
            raise ValueError(
                f"Strategy '{name}' is already registered — pass "
                f"override=True if replacing it is deliberate."
            )
        self._strategies[name] = StrategySpec(name=name, factory=factory, description=description)
        logger.info(f"StrategyRegistry: registered '{name}'")

    def get(self, name: str) -> StrategySpec:
        if name not in self._strategies:
            available = ", ".join(sorted(self._strategies)) or "(none registered)"
            raise KeyError(f"Unknown strategy '{name}'. Available: {available}")
        return self._strategies[name]

    def build(self, name: str, **kwargs):
        """Resolve `name` and call its factory with `kwargs`. Any
        ValueError the factory raises for missing/invalid kwargs
        propagates unchanged — callers (main.py) decide how to handle
        a build failure, this method doesn't swallow it."""
        return self.get(name).factory(**kwargs)

    def list_strategies(self) -> List[dict]:
        return [
            {"name": s.name, "description": s.description}
            for s in sorted(self._strategies.values(), key=lambda s: s.name)
        ]

    def is_registered(self, name: str) -> bool:
        return name in self._strategies


# ── Module-level singleton (the registry main.py / config actually use) ────
_REGISTRY = StrategyRegistry()


def register_strategy(
    name: str, factory: StrategyFactory, description: str = "", override: bool = False
) -> None:
    _REGISTRY.register(name, factory, description=description, override=override)


def get_strategy(name: str) -> StrategyFactory:
    """Return the raw factory for `name` (mainly for tests/introspection —
    main.py should prefer build_strategy())."""
    return _REGISTRY.get(name).factory


def build_strategy(name: str, **kwargs):
    return _REGISTRY.build(name, **kwargs)


def list_strategies() -> List[dict]:
    return _REGISTRY.list_strategies()


# ── Built-in strategy: portfolio_signal_provider (default) ─────────────────

def _build_portfolio_signal_provider(**kwargs):
    from execution.portfolio_signal_provider import PortfolioSignalProvider

    data_provider = kwargs.get("data_provider")
    if data_provider is None:
        raise ValueError("'portfolio_signal_provider' requires data_provider=")
    return PortfolioSignalProvider(
        data_provider=data_provider,
        regime_engine=kwargs.get("regime_engine"),
        smc_engine=kwargs.get("smc_engine"),
        volume_engine=kwargs.get("volume_engine"),
        context_builder=kwargs.get("context_builder"),
        confidence_engine=kwargs.get("confidence_engine"),
    )


# ── Built-in strategy: smc_oi_regime (legacy, single-symbol only) ──────────

class SMCOIRegimeStrategyAdapter:
    """Adapts execution/strategy.py's SMC_OI_Regime_Strategy (returns a
    bare (direction, stop_loss, take_profit) tuple, no entry price) to
    this project's SignalProvider contract, which needs a full
    ExecutionSignal including entry_price. The underlying strategy
    stashes its last DecisionResult (which does carry entry_price) on
    `.last_decision` after every generate_signal() call — read from
    there rather than inventing an entry price.

    NOT symbol-aware — see this module's docstring "smc_oi_regime"
    section. The `symbol` parameter exists only to satisfy the
    SignalProvider callable shape.
    """

    def __init__(self, decision_engine, regime_engine, smc_engine, volume_engine, data_provider) -> None:
        from execution.strategy import SMC_OI_Regime_Strategy

        self._strategy = SMC_OI_Regime_Strategy(
            decision_engine=decision_engine,
            regime_engine=regime_engine,
            smc_engine=smc_engine,
            volume_engine=volume_engine,
            data_provider=data_provider,
        )

    def get_signal(self, symbol: str) -> Optional[ExecutionSignal]:
        direction, stop_loss, take_profit = self._strategy.generate_signal()
        if direction == 0:
            return None
        last = self._strategy.last_decision
        entry_price = getattr(last, "entry_price", 0.0) if last is not None else 0.0
        if not entry_price:
            # Mirrors PortfolioSignalProvider's own "no entry price ->
            # no trade" handling (see its _compute_signal()).
            return None
        return ExecutionSignal(
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )

    def __call__(self, symbol: str) -> Optional[ExecutionSignal]:
        return self.get_signal(symbol)


def _build_smc_oi_regime_adapter(**kwargs):
    required = ("decision_engine", "regime_engine", "smc_engine", "volume_engine", "data_provider")
    missing = [k for k in required if kwargs.get(k) is None]
    if missing:
        raise ValueError(
            f"'smc_oi_regime' strategy requires {missing} — note this "
            f"strategy is single-symbol-shaped and not safe for "
            f"ExecutionScheduler's multi-symbol path (see class docstring)."
        )
    return SMCOIRegimeStrategyAdapter(**{k: kwargs[k] for k in required})


register_strategy(
    "portfolio_signal_provider",
    _build_portfolio_signal_provider,
    description=(
        "Multi-symbol signal provider (V16 Phase 2F). Reuses the live "
        "single-symbol pipeline (RegimeEngine->SMCEngine->VolumeEngine->"
        "MarketContextBuilder->ConfidenceEngine) for an arbitrary symbol. "
        "Default — safe for ExecutionScheduler's per-symbol calls."
    ),
)

register_strategy(
    "smc_oi_regime",
    _build_smc_oi_regime_adapter,
    description=(
        "Legacy conor19w-compatible adapter around BrainDecisionEngine "
        "(execution/strategy.py). NOT symbol-aware — always reflects the "
        "single globally-configured symbol regardless of the `symbol` "
        "argument. Do not select for ExecutionScheduler; kept for "
        "plugin-system completeness / future single-symbol standalone use."
    ),
)
