"""
Execution Layer: SMC_OI_Regime_Strategy

Adapter that runs the Brain pipeline and returns the signal tuple expected by
the conor19w Binance-Futures-Trading-Bot:

    Trade_Direction : int   1=Long · -1=Short · 0=No trade
    stop_loss_val   : float
    take_profit_val : float

Usage
-----
strategy = SMC_OI_Regime_Strategy(
    decision_engine, regime_engine, smc_engine, volume_engine, data_provider
)
direction, sl, tp = strategy.generate_signal()
"""

from __future__ import annotations

import os
import sys

# ── Optionally add conor19w bot to sys.path ───────────────────────────────────
_HERE        = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_VENDOR_BOT  = os.path.join(_HERE, "vendors", "binance_futures_bot")
if os.path.isdir(_VENDOR_BOT) and _VENDOR_BOT not in sys.path:
    sys.path.insert(0, _VENDOR_BOT)

from utils.logger import get_logger

logger = get_logger(__name__)


class SMC_OI_Regime_Strategy:
    """
    Strategy injector compatible with conor19w/Binance-Futures-Trading-Bot.

    Dependency-injected: no hard imports at module level so the pipeline
    can be tested without live API keys.
    """

    def __init__(
        self,
        decision_engine,    # BrainDecisionEngine
        regime_engine,      # RegimeEngine
        smc_engine,         # SMCEngine
        volume_engine,      # VolumeEngine
        data_provider,      # BinanceDataProvider
    ) -> None:
        self.decision_engine = decision_engine
        self.regime_engine   = regime_engine
        self.smc_engine      = smc_engine
        self.volume_engine   = volume_engine
        self.data_provider   = data_provider
        self._last_decision  = None
        logger.info("SMC_OI_Regime_Strategy initialised")

    # ── conor19w-compatible interface ─────────────────────────────────────

    def generate_signal(self) -> tuple[int, float, float]:
        """
        Run one full brain cycle and return the conor19w-style tuple.

        Returns
        -------
        (Trade_Direction, stop_loss_val, take_profit_val)
        """
        try:
            market = self.data_provider.get_all_market_data()
            ohlcv  = market["ohlcv"]

            # Regime (H1)
            regime = self.regime_engine.classify(ohlcv["h1"])

            # Skip highly volatile regimes immediately
            if regime.regime == "VOLATILE" and regime.confidence > 0.75:
                logger.info(f"Skipping VOLATILE regime conf={regime.confidence:.2f}")
                return 0, 0.0, 0.0

            # SMC multi-timeframe
            smc_signals = self.smc_engine.analyze_mtf(ohlcv)

            # Volume (M15)
            vol_signals = self.volume_engine.analyze(ohlcv["m15"])

            # Brain decision
            decision = self.decision_engine.decide(
                smc_signals   = smc_signals,
                volume_signals = vol_signals,
                regime_result  = regime,
                market_data    = market,
                df_m15         = ohlcv["m15"],
            )

            self._last_decision = decision

            if decision.action == "LONG":
                return 1, decision.stop_loss, decision.take_profit
            if decision.action == "SHORT":
                return -1, decision.stop_loss, decision.take_profit

            return 0, 0.0, 0.0

        except Exception as exc:
            logger.error(f"generate_signal error: {exc}", exc_info=True)
            return 0, 0.0, 0.0

    @property
    def last_decision(self):
        """Expose the most recent DecisionResult for journaling."""
        return self._last_decision
