"""
execution/smc_oi_regime_multi.py — V16 Phase 4C: Symbol-Aware SMC/OI
Regime Strategy Adapter

Makes the SMC/OI-regime pipeline (`decision/brain_decision_engine.py`'s
BrainDecisionEngine, driven by RegimeEngine -> SMCEngine -> VolumeEngine)
usable in ExecutionScheduler's multi-symbol live path, where today only
`"portfolio_signal_provider"` is safe (see execution/strategy_registry.py's
module docstring and docs/architecture.md §25's "Scope boundary").

Root cause this fixes
----------------------
`execution/strategy.py`'s `SMC_OI_Regime_Strategy.generate_signal()` calls
`self.data_provider.get_all_market_data()`, which takes no symbol argument
and always reflects the single globally-configured symbol
(`config/settings.py`'s `SYMBOL`). That is the ONLY thing blocking
multi-symbol use — the rest of the pipeline it drives
(`regime_engine.classify` -> `smc_engine.analyze_mtf` ->
`volume_engine.analyze` -> `decision_engine.decide`) consumes only the
OHLCV/market dict handed to it, never `self.data_provider` directly.

`data/binance_provider.py`'s `get_market_data_for(symbol)` (added V16
Phase 2F for exactly this reason — see `PortfolioSignalProvider`) returns
the identical shape `get_all_market_data()` does, so swapping the call
site is sufficient. That swap is deliberately NOT made inside
`SMC_OI_Regime_Strategy` itself — that class is intentionally
single-symbol/global (other code may depend on that exact contract; see
`execution/strategy_registry.py`'s `SMCOIRegimeStrategyAdapter`, which
still wraps it unchanged and stays registered as `"smc_oi_regime"` for
that reason). This module is an additive, parallel adapter, not a
modification of that class.

One correction to the pipeline as re-implemented here, vs. a literal
copy of `SMC_OI_Regime_Strategy.generate_signal()`
-----------------------------------------------------------------------
`generate_signal()` calls `self.regime_engine.classify(ohlcv["h1"])` with
no `symbol=`. That is correct for a single-global-symbol caller, but
`RegimeEngine.classify()` has held an internal per-symbol-keyed HMM model
cache since V16 Phase 4B Step 3A specifically so multi-symbol callers can
give each symbol its own independently-fit model — passing `symbol=` is
what activates that cache; omitting it silently pools every symbol onto
one shared model (`RegimeEngine.classify()`'s own docstring, and
`portfolio_signal_provider.py`'s module docstring, both document this
explicitly). `PortfolioSignalProvider` already passes `symbol=symbol`
here for that reason, and `tests/test_portfolio_signal_provider.py::
TestSharedEngineInjection::test_injected_regime_engine_is_used` asserts
it does. Since this module exists specifically to make the pipeline safe
for multi-symbol use, omitting `symbol=` here would reproduce the same
cross-symbol state-pooling bug this module is meant to avoid — so this
adapter passes it, unlike the literal single-symbol call site it
otherwise mirrors.

Usage
-----
adapter = SMCOIRegimeMultiAdapter(
    decision_engine, regime_engine, smc_engine, volume_engine, data_provider
)
signal = adapter.get_signal("ETHUSDT")  # or adapter("ETHUSDT")
"""

from __future__ import annotations

from execution.execution_orchestrator import ExecutionSignal
from utils.logger import get_logger

logger = get_logger(__name__)


class SMCOIRegimeMultiAdapter:
    """Callable matching execution/execution_orchestrator.py's
    SignalProvider = Callable[[str], Optional[ExecutionSignal]] contract
    exactly — safe to select for ExecutionScheduler's per-symbol calls,
    unlike `"smc_oi_regime"` / `SMCOIRegimeStrategyAdapter`.

    Constructed with the same five dependencies
    `SMCOIRegimeStrategyAdapter` already takes (decision_engine,
    regime_engine, smc_engine, volume_engine, data_provider). Never
    raises: any failure anywhere in the pipeline (bad/incomplete data, a
    transient engine error) is logged and treated as "no signal this
    cycle" for that symbol, matching this project's "safety wrapping at
    every touchpoint" rule and `PortfolioSignalProvider.get_signal()`'s
    identical documented contract — one bad symbol in a multi-symbol
    batch can never take down the whole cycle.
    """

    def __init__(self, decision_engine, regime_engine, smc_engine, volume_engine, data_provider) -> None:
        self.decision_engine = decision_engine
        self.regime_engine = regime_engine
        self.smc_engine = smc_engine
        self.volume_engine = volume_engine
        self.data_provider = data_provider
        logger.info("SMCOIRegimeMultiAdapter initialised")

    def get_signal(self, symbol: str) -> ExecutionSignal | None:
        try:
            return self._compute_signal(symbol)
        except Exception as exc:
            logger.error(f"SMCOIRegimeMultiAdapter: signal computation failed for {symbol}: {exc}", exc_info=True)
            return None

    def _compute_signal(self, symbol: str) -> ExecutionSignal | None:
        market = self.data_provider.get_market_data_for(symbol)
        ohlcv = market.get("ohlcv", {})
        if "h1" not in ohlcv or "m15" not in ohlcv:
            logger.warning(
                f"SMCOIRegimeMultiAdapter: incomplete OHLCV for {symbol} (have: {list(ohlcv.keys())})"
            )
            return None

        # V16 Phase 4B Step 3A/3C: symbol= activates RegimeEngine's
        # per-symbol HMM cache — see module docstring "One correction" above.
        regime = self.regime_engine.classify(ohlcv["h1"], symbol=symbol)

        if regime.regime == "VOLATILE" and regime.confidence > 0.75:
            logger.info(
                f"SMCOIRegimeMultiAdapter: skipping VOLATILE regime "
                f"conf={regime.confidence:.2f} for {symbol}"
            )
            return None

        smc_signals = self.smc_engine.analyze_mtf(ohlcv)
        volume_signals = self.volume_engine.analyze(ohlcv["m15"])

        decision = self.decision_engine.decide(
            smc_signals=smc_signals,
            volume_signals=volume_signals,
            regime_result=regime,
            market_data=market,
            df_m15=ohlcv["m15"],
        )

        if decision.action not in ("LONG", "SHORT"):
            return None

        # Mirrors SMCOIRegimeStrategyAdapter's own "no entry price -> no
        # trade" rule (execution/strategy_registry.py), and
        # PortfolioSignalProvider's identical rule — unlike that adapter,
        # this class calls decision_engine.decide() itself, so it reads
        # entry_price directly off the DecisionResult it already has
        # rather than needing a separate .last_decision lookup.
        entry_price = getattr(decision, "entry_price", 0.0)
        if not entry_price:
            return None

        direction = 1 if decision.action == "LONG" else -1
        return ExecutionSignal(
            direction=direction,
            entry_price=entry_price,
            stop_loss=decision.stop_loss,
            take_profit=decision.take_profit,
        )

    def __call__(self, symbol: str) -> ExecutionSignal | None:
        return self.get_signal(symbol)
