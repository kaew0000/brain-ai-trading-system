"""
Intelligence Layer: Market Context Builder

Aggregates outputs from all independent analysis layers into a single
`market_context` dictionary that the Decision Engine and Confidence Engine
consume. This is the glue between Layer 1-7 and Layer 8.

Output schema
-------------
{
  "symbol":        str,
  "timestamp":     str (ISO-8601),
  "mark_price":    float,

  // Layer 3 — Regime
  "regime":        str,             # TREND | RANGE | VOLATILE | SQUEEZE
  "regime_conf":   float,           # 0-1

  // Layer 4 — Trend
  "trend_bias":    str,             # LONG_BIAS | SHORT_BIAS | NEUTRAL
  "trend_strength":str,             # STRONG | MODERATE | WEAK
  "trend_data":    dict,            # full TrendResult.to_dict()

  // Layer 5 — SMC (per timeframe)
  "smc_h4":        dict,
  "smc_h1":        dict,
  "smc_m15":       dict,

  // Layer 6 — Futures Intelligence
  "futures":       dict,            # full FuturesIntelResult.to_dict()
  "futures_signal":str,             # LONG | SHORT | NEUTRAL
  "futures_condition": str,

  // Layer 7 — Volume
  "volume":        dict,            # VolumeSignals.to_dict()

  // Layer 2 — Market Intelligence (optional; None if not yet wired)
  "fear_greed":    int | None,
  "macro_risk":    bool,
  "risk_on":       bool,
  "correlation":   dict | None,

  // Convenience flags for Decision Engine
  "blocks_long":   bool,
  "blocks_short":  bool,
  "mtf_direction": str,             # LONG | SHORT | ""
  "mtf_aligned":   bool,
}

API surface: /api/signals includes market_context as raw_features
"""

from __future__ import annotations

from datetime import datetime, timezone

from config.settings import settings
from utils.logger import get_logger
from trend.trend_engine import TrendEngine, TrendResult
from futures.futures_intel_engine import FuturesIntelEngine, FuturesIntelResult
from features.smc_engine import SMCSignals
from features.volume_engine import VolumeSignals
from regime.regime_engine import RegimeResult

logger = get_logger(__name__)


class MarketContextBuilder:
    """
    Stateless builder — call build() every decision cycle.

    The builder does NOT fetch data; it receives already-computed engine
    outputs and assembles the unified context dict.

    Trend analysis (Layer 4) is computed inside build() because the
    TrendEngine is a pure function of OHLCV data that is always available.
    All other engines are computed upstream and passed in.
    """

    def __init__(self) -> None:
        self._trend_engine   = TrendEngine()
        self._futures_engine = FuturesIntelEngine()
        logger.info("MarketContextBuilder ready")

    # ── Public ────────────────────────────────────────────────────────────────

    def build(
        self,
        market_data:    dict,
        smc_signals:    dict[str, SMCSignals],     # {"h4": ..., "h1": ..., "m15": ...}
        volume_signals: VolumeSignals,
        regime_result:  RegimeResult,
        ohlcv_h4=None,                              # pd.DataFrame (for trend analysis)
        ohlcv_h1=None,
        intelligence:   dict | None = None,      # Layer 2 output (optional)
        symbol:         str | None = None,       # V16 Phase 2F: explicit symbol for
                                                      # multi-symbol callers; defaults to
                                                      # settings.SYMBOL (the single-symbol
                                                      # legacy caller's implicit behavior,
                                                      # unchanged) when omitted.
    ) -> dict:
        """
        Assemble the full market context.

        Parameters
        ----------
        market_data   : dict from BinanceDataProvider.get_all_market_data()
        smc_signals   : per-timeframe SMCSignals from SMCEngine
        volume_signals: VolumeSignals from VolumeEngine
        regime_result : RegimeResult from RegimeEngine
        ohlcv_h4      : H4 DataFrame (used for trend analysis; H1 if None)
        ohlcv_h1      : H1 DataFrame (fallback if H4 not provided)
        intelligence  : Layer 2 market intelligence dict (optional)
        symbol        : symbol this context is for. Omit for the existing
                         single-symbol caller (main.py) — defaults to
                         settings.SYMBOL, identical to the pre-Phase-2F
                         behavior. Multi-symbol callers (execution/
                         portfolio_signal_provider.py) must pass this
                         explicitly or every context would silently claim
                         to be for settings.SYMBOL regardless of which
                         symbol's data was actually analyzed.
        """

        # ── Trend (Layer 4) ───────────────────────────────────────────────────
        trend_df = ohlcv_h4 if ohlcv_h4 is not None else ohlcv_h1
        mark_price = float(market_data.get("mark_price", 0.0))

        trend: TrendResult = (
            self._trend_engine.analyse(trend_df, current_price=mark_price)
            if trend_df is not None else TrendResult()
        )

        # ── Futures Intelligence (Layer 6) ────────────────────────────────────
        futures: FuturesIntelResult = self._futures_engine.analyse(market_data)

        # ── SMC summaries per timeframe ───────────────────────────────────────
        h4  = smc_signals.get("h4",  SMCSignals())
        h1  = smc_signals.get("h1",  SMCSignals())
        m15 = smc_signals.get("m15", SMCSignals())

        # ── MTF direction consensus ───────────────────────────────────────────
        mtf_dir, mtf_aligned = _mtf_direction(h4, h1, m15)

        # ── Layer 2 defaults ──────────────────────────────────────────────────
        intel = intelligence or {}

        ctx: dict = {
            "symbol":     symbol if symbol is not None else settings.SYMBOL,
            "timestamp":  datetime.now(timezone.utc).isoformat(),
            "mark_price": mark_price,

            # Layer 3
            "regime":       regime_result.regime,
            "regime_conf":  round(regime_result.confidence, 4),
            "regime_data":  regime_result.to_dict(),

            # Layer 4
            "trend_bias":     trend.bias,
            "trend_strength": trend.strength,
            "trend_conf":     trend.confidence,
            "trend_data":     trend.to_dict(),

            # Layer 5 — SMC per TF
            "smc_h4":  _smc_to_dict(h4),
            "smc_h1":  _smc_to_dict(h1),
            "smc_m15": _smc_to_dict(m15),

            # Layer 6
            "futures":           futures.to_dict(),
            "futures_signal":    futures.signal,
            "futures_condition": futures.condition,
            "futures_conf":      round(futures.confidence, 4),

            # Layer 7
            "volume": _volume_to_dict(volume_signals),

            # Raw futures scalars (used by DecisionEngine compatibility layer)
            "oi_delta":         float(market_data.get("oi_delta", 0.0)),
            "funding_rate":     float(market_data.get("funding_rate", 0.0)),
            "long_short_ratio": market_data.get("long_short_ratio", {}),
            "taker_ratio":      market_data.get("taker_ratio", {}),

            # Layer 2 (optional)
            "fear_greed":  intel.get("fear_greed"),
            "macro_risk":  bool(intel.get("macro_risk", False)),
            "risk_on":     bool(intel.get("risk_on", True)),
            "correlation": intel.get("correlation"),
            "news_sentiment": intel.get("news_sentiment"),

            # Convenience flags
            "blocks_long":    futures.blocks_long(),
            "blocks_short":   futures.blocks_short(),
            "mtf_direction":  mtf_dir,
            "mtf_aligned":    mtf_aligned,
        }

        logger.debug(
            f"MarketContext built | regime={ctx['regime']} trend={ctx['trend_bias']} "
            f"futures={ctx['futures_signal']} mtf={mtf_dir}(aligned={mtf_aligned})"
        )
        return ctx


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_bullish(bias: str) -> bool:
    return "ullish" in bias or bias == "LONG_BIAS"

def _is_bearish(bias: str) -> bool:
    return "earish" in bias or bias == "SHORT_BIAS"

def _mtf_direction(h4: SMCSignals, h1: SMCSignals, m15: SMCSignals) -> tuple[str, bool]:
    bull = sum([_is_bullish(h4.trend_bias), _is_bullish(h1.trend_bias), _is_bullish(m15.trend_bias)])
    bear = sum([_is_bearish(h4.trend_bias), _is_bearish(h1.trend_bias), _is_bearish(m15.trend_bias)])

    if bull == 3: return "LONG",  True
    if bear == 3: return "SHORT", True
    if bull >= 2: return "LONG",  False
    if bear >= 2: return "SHORT", False
    if _is_bullish(m15.trend_bias) and _is_bullish(h4.trend_bias): return "LONG",  False
    if _is_bearish(m15.trend_bias) and _is_bearish(h4.trend_bias): return "SHORT", False
    return "", False


def _smc_to_dict(sig: SMCSignals) -> dict:
    return {
        "bos":          sig.bos,
        "bos_dir":      sig.bos_direction,
        "choch":        sig.choch,
        "choch_dir":    sig.choch_direction,
        "fvg":          sig.fvg,
        "fvg_dir":      sig.fvg_direction,
        "ob":           sig.ob,
        "ob_dir":       sig.ob_direction,
        "ob_top":       sig.ob_top,
        "ob_bottom":    sig.ob_bottom,
        "trend_bias":   sig.trend_bias,
        "liquidity_high": sig.liquidity_high,
        "liquidity_low":  sig.liquidity_low,
        "prev_high":    sig.prev_high,
        "prev_low":     sig.prev_low,
    }


def _volume_to_dict(vol: VolumeSignals) -> dict:
    return {
        "volume_spike":      vol.volume_spike,
        "volume_ratio":      round(vol.volume_ratio, 4),
        "obv_direction":     vol.obv_direction,
        "breakout_confirmed":vol.breakout_confirmed,
        "score":             vol.score,
    }
