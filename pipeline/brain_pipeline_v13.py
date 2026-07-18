"""
Pipeline Layer: BrainPipelineV13
=================================
Drop-in replacement for BOTH BrainDecisionEngine and SMC_OI_Regime_Strategy.

Wiring
------
                              ┌─────────────────────────┐
SMCEngine ──►                 │                         │
VolumeEngine ──►              │  MarketContextBuilder   │──► unified context dict
RegimeEngine ──►              │                         │
BinanceDataProvider ──►       └─────────────────────────┘
                                          │
                                          ▼
                              ┌─────────────────────────┐
                              │   ConfidenceEngine       │──► ConfidenceResult
                              └─────────────────────────┘
                                          │
                   SL/TP calc             │
BrainDecisionEngine (legacy) ─────────── ┘

Public interface
----------------
pipeline.decide(smc_signals, volume_signals, regime_result, market_data, df_m15)
    → ConfidenceResult     (drop-in for BrainDecisionEngine.decide())

pipeline.generate_signal(market_data, smc_signals, volume_signals, regime_result, ohlcv)
    → (int, float, float)  (drop-in for SMC_OI_Regime_Strategy.generate_signal())

pipeline.last_decision     property → most recent ConfidenceResult
"""

from __future__ import annotations

from typing import Optional, Tuple

import pandas as pd

from decision.brain_decision_engine import BrainDecisionEngine
from decision.confidence_engine import ConfidenceEngine
from intelligence.market_context_builder import MarketContextBuilder
from features.smc_engine import SMCSignals
from features.volume_engine import VolumeSignals
from regime.regime_engine import RegimeResult
from utils.logger import get_logger

logger = get_logger(__name__)


class BrainPipelineV13:
    """
    Unified V13 pipeline.

    Instantiate once and pass to main trading loop; reuse across cycles.
    Thread-safe as long as each cycle calls decide() sequentially (no
    concurrent decide() calls — same contract as v1 BrainDecisionEngine).
    """

    def __init__(
        self,
        weights: Optional[dict[str, float]] = None,
    ) -> None:
        self._context_builder  = MarketContextBuilder()
        self._confidence_engine = ConfidenceEngine(weights=weights)
        self._decision_engine  = BrainDecisionEngine()   # SL/TP only
        self._last_result      = None
        logger.info("BrainPipelineV13 ready")

    # ── Main entry (replaces BrainDecisionEngine.decide) ─────────────────────

    def decide(
        self,
        smc_signals:    dict[str, SMCSignals],
        volume_signals: VolumeSignals,
        regime_result:  RegimeResult,
        market_data:    dict,
        df_m15:         pd.DataFrame,
    ):
        """
        Run one full pipeline cycle and return a ConfidenceResult.

        Parameters match BrainDecisionEngine.decide() exactly so callers
        in main.py require zero changes beyond the class swap.

        Returns
        -------
        ConfidenceResult  (has .action, .score, .max_score, .direction,
                           .confidence, .entry_price, .stop_loss, .take_profit,
                           .oi_delta, .funding_rate, .mtf_aligned, .regime,
                           .blocked, .block_reasons, .breakdown)
        """
        from decision.confidence_engine import ConfidenceResult  # avoid circ-import

        mark_price = float(market_data.get("mark_price", 0.0))
        ohlcv      = market_data.get("ohlcv", {})

        # ── 1. Build unified market context ───────────────────────────────────
        context = self._context_builder.build(
            market_data    = market_data,
            smc_signals    = smc_signals,
            volume_signals = volume_signals,
            regime_result  = regime_result,
            ohlcv_h4       = ohlcv.get("h4"),
            ohlcv_h1       = ohlcv.get("h1"),
        )

        direction   = context.get("mtf_direction", "")
        mtf_aligned = bool(context.get("mtf_aligned", False))

        # ── 2. Compute SL / TP via legacy engine ──────────────────────────────
        # The legacy BrainDecisionEngine owns the OB / ATR SL-TP logic; we
        # reuse it for that single responsibility and discard its score.
        sl = tp = 0.0
        if direction and mark_price > 0:
            try:
                legacy = self._decision_engine.decide(
                    smc_signals    = smc_signals,
                    volume_signals = volume_signals,
                    regime_result  = regime_result,
                    market_data    = market_data,
                    df_m15         = df_m15,
                )
                sl = legacy.stop_loss
                tp = legacy.take_profit
            except Exception as exc:
                logger.warning(f"Legacy SL/TP computation failed: {exc}")

        # ── 3. Score with ConfidenceEngine ────────────────────────────────────
        result: ConfidenceResult = self._confidence_engine.score(
            market_context = context,
            direction      = direction,
            entry_price    = mark_price,
            stop_loss      = sl,
            take_profit    = tp,
            mtf_aligned    = mtf_aligned,
        )

        # ── 4. Attach extras needed by TradeRecord.from_decision() ────────────
        result.oi_delta     = float(market_data.get("oi_delta",     0.0))
        result.funding_rate = float(market_data.get("funding_rate", 0.0))
        # score alias → raw 9-point value (used by main.py logger and journal)
        result.score        = result.raw_score

        self._last_result = result

        logger.info(
            f"BrainPipelineV13 | action={result.action} "
            f"conf={result.confidence}% score={result.raw_score}/9 "
            f"dir={direction} mtf={mtf_aligned} regime={result.regime}"
        )
        return result

    # ── conor19w-style adapter (replaces SMC_OI_Regime_Strategy) ─────────────

    def generate_signal(
        self,
        market_data:    dict,
        smc_signals:    dict[str, SMCSignals],
        volume_signals: VolumeSignals,
        regime_result:  RegimeResult,
        df_m15:         pd.DataFrame,
    ) -> Tuple[int, float, float]:
        """
        Run pipeline and return (Trade_Direction, stop_loss, take_profit).
        Compatible with conor19w/Binance-Futures-Trading-Bot interface.
        """
        try:
            result = self.decide(
                smc_signals    = smc_signals,
                volume_signals = volume_signals,
                regime_result  = regime_result,
                market_data    = market_data,
                df_m15         = df_m15,
            )
            if result.action == "LONG":
                return  1, result.stop_loss, result.take_profit
            if result.action == "SHORT":
                return -1, result.stop_loss, result.take_profit
            return 0, 0.0, 0.0

        except Exception as exc:
            logger.error(f"generate_signal error: {exc}", exc_info=True)
            return 0, 0.0, 0.0

    # ── Weight hot-swap ───────────────────────────────────────────────────────

    def update_weights(self, weights: dict[str, float]) -> None:
        """Apply new category weights to the ConfidenceEngine at runtime."""
        self._confidence_engine.update_weights(weights)
        logger.info(f"BrainPipelineV13 weights updated: {weights}")

    # ── Compat property ───────────────────────────────────────────────────────

    @property
    def last_decision(self):
        """Most recent ConfidenceResult (None before first cycle)."""
        return self._last_result
