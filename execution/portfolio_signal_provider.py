"""
execution/portfolio_signal_provider.py — V16 Phase 2F: Execution
Scheduler + Multi-Symbol Signals

Reuses the SAME decision pipeline main.py's live single-symbol trading
loop already uses today — RegimeEngine -> SMCEngine -> VolumeEngine ->
MarketContextBuilder (which internally also runs TrendEngine and
FuturesIntelEngine) -> ConfidenceEngine. Confirmed by reading
run_trading_cycle() in main.py, NOT by assumption: this is deliberately
NOT built on execution/strategy.py's SMC_OI_Regime_Strategy /
decision/brain_decision_engine.py's BrainDecisionEngine — that pipeline
exists in this codebase (kept for compatibility with an external
conor19w-style bot framework, per its own docstring) but is never
instantiated anywhere in main.py's actual bootstrap or trading cycle.
Building this module on that pipeline would have silently produced
signals that don't match what the live bot actually does.

Every one of the 6 pipeline classes used here is stateless / a pure
function of the data passed to each call — confirmed by inspecting each
one's __init__ and call signature, not assumed:
  - RegimeEngine.classify(df), SMCEngine.analyze_mtf(ohlcv),
    VolumeEngine.analyze(df): no symbol reference anywhere.
  - TrendEngine.analyse(df, ...), FuturesIntelEngine.analyse(market_data):
    same.
  - MarketContextBuilder.build(...): was the ONE place a symbol leaked in
    implicitly (hardcoded settings.SYMBOL into the output dict) — fixed
    additively in this same phase by giving build() an optional `symbol`
    parameter; single-symbol callers that omit it are completely
    unaffected.
  - ConfidenceEngine.score(...): pure function of a market_context dict.

Because none of them hold per-symbol state, ONE shared instance of each
is constructed once and reused for every symbol this provider is asked
about — there is no per-symbol sub-instance to manage, unlike
ExecutionCoordinator's per-symbol TradeManager cache (which exists
specifically because TradeManager DOES hold per-symbol state: open
orders, position tracking).

_derive_levels() (turns direction + mark_price + context into
entry/stop-loss/take-profit) is imported directly from main.py rather
than duplicated here — tests/test_execution_factory.py already does
exactly this (`from main import _derive_levels`), which is existing
proof the import is safe: main.py's module-level code is guarded by
`if __name__ == "__main__":`, so importing it never runs the bot.
"""
from __future__ import annotations

from typing import Optional

from data.binance_provider import BinanceDataProvider
from decision.confidence_engine import ConfidenceEngine
from execution.execution_orchestrator import ExecutionSignal
from features.smc_engine import SMCEngine
from features.volume_engine import VolumeEngine
from intelligence.market_context_builder import MarketContextBuilder
from regime.regime_engine import RegimeEngine
from utils.logger import get_logger

logger = get_logger(__name__)


class PortfolioSignalProvider:
    """Callable matching execution/execution_orchestrator.py's
    SignalProvider = Callable[[str], Optional[ExecutionSignal]] contract
    exactly. Construct once (typically in the same bootstrap that builds
    ExecutionOrchestrator); call get_signal(symbol) — or the instance
    itself — for every symbol PortfolioManager selected in a cycle.
    """

    def __init__(
        self,
        data_provider: BinanceDataProvider,
        regime_engine: Optional[RegimeEngine] = None,
        smc_engine: Optional[SMCEngine] = None,
        volume_engine: Optional[VolumeEngine] = None,
        context_builder: Optional[MarketContextBuilder] = None,
        confidence_engine: Optional[ConfidenceEngine] = None,
    ) -> None:
        # data_provider is required — no sensible default, it's the one
        # thing here that actually talks to Binance. Everything else
        # defaults to a fresh instance if not supplied, but production
        # wiring should pass the SAME instances main.py's bootstrap
        # already constructs (sys["regime_engine"], sys["smc_engine"],
        # sys["volume_engine"]) rather than building duplicates — purely
        # to avoid pointless duplicate construction, since (as this
        # module's docstring covers) none of them hold state that would
        # make sharing incorrect.
        self.data_provider = data_provider
        self.regime_engine = regime_engine or RegimeEngine(use_hmm=True)
        self.smc_engine = smc_engine or SMCEngine()
        self.volume_engine = volume_engine or VolumeEngine()
        # MarketContextBuilder constructs its own internal TrendEngine/
        # FuturesIntelEngine (see that class's __init__) — not
        # duplicated or re-passed here.
        self.context_builder = context_builder or MarketContextBuilder()
        self.confidence_engine = confidence_engine or ConfidenceEngine()
        logger.info("PortfolioSignalProvider ready")

    def get_signal(self, symbol: str) -> Optional[ExecutionSignal]:
        """Compute a trading signal for `symbol` using the exact pipeline
        main.py's live single-symbol loop uses, pointed at an arbitrary
        symbol instead of settings.SYMBOL. Never raises — any failure
        anywhere in the pipeline (bad data, a transient engine error) is
        logged and treated as "no signal this cycle" for this symbol,
        so one bad symbol in a multi-symbol batch can never take down
        the whole cycle. Matches this project's own "safety wrapping at
        every touchpoint" rule."""
        try:
            return self._compute_signal(symbol)
        except Exception as exc:
            logger.error(f"PortfolioSignalProvider: signal computation failed for {symbol}: {exc}")
            return None

    def _compute_signal(self, symbol: str) -> Optional[ExecutionSignal]:
        from main import _derive_levels  # see module docstring

        market = self.data_provider.get_market_data_for(symbol)
        ohlcv = market.get("ohlcv", {})
        if "h1" not in ohlcv or "m15" not in ohlcv:
            logger.warning(f"PortfolioSignalProvider: incomplete OHLCV for {symbol} (have: {list(ohlcv.keys())})")
            return None

        regime = self.regime_engine.classify(ohlcv["h1"])
        smc_signals = self.smc_engine.analyze_mtf(ohlcv)
        volume_signals = self.volume_engine.analyze(ohlcv["m15"])

        ctx = self.context_builder.build(
            market_data=market,
            smc_signals=smc_signals,
            volume_signals=volume_signals,
            regime_result=regime,
            ohlcv_h4=ohlcv.get("h4"),
            ohlcv_h1=ohlcv.get("h1"),
            symbol=symbol,
        )

        direction = ctx.get("mtf_direction", "")
        mark_price = ctx.get("mark_price", 0.0)
        if not direction or not mark_price:
            return None  # no MTF consensus this cycle — same "no trade" outcome main.py's own loop treats it as

        entry, stop_loss, take_profit = _derive_levels(direction, mark_price, ctx)
        if not entry:
            return None

        decision = self.confidence_engine.score(
            market_context=ctx,
            direction=direction,
            entry_price=entry,
            stop_loss=stop_loss,
            take_profit=take_profit,
            mtf_aligned=ctx.get("mtf_aligned", False),
        )

        if decision.action == "LONG":
            return ExecutionSignal(direction=1, entry_price=entry, stop_loss=stop_loss, take_profit=take_profit)
        if decision.action == "SHORT":
            return ExecutionSignal(direction=-1, entry_price=entry, stop_loss=stop_loss, take_profit=take_profit)
        # WAIT / SKIP / BLOCKED all mean "no trade this symbol, this cycle" — identical
        # to how main.py's own single-symbol loop treats these three outcomes.
        return None

    def __call__(self, symbol: str) -> Optional[ExecutionSignal]:
        return self.get_signal(symbol)
