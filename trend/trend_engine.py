"""
Trend Engine (Layer 4)

Dedicated engine for trend analysis, separated from the Regime Engine (Layer 3)
which handles market state (TREND/RANGE/VOLATILE/SQUEEZE).

The Trend Engine answers: "What is the current directional bias?"

Indicators
----------
EMA 20  — short-term momentum
EMA 50  — medium-term trend
EMA 200 — long-term structure (bull/bear market)
VWAP    — intraday institutional fair value (session VWAP on M15)
ADX     — trend strength (14-period; threshold configurable)
Slope   — linear regression slope of EMA50 over last N bars (normalized)

Output: TrendResult
-------------------
{
    "bias":          "LONG_BIAS" | "SHORT_BIAS" | "NEUTRAL",
    "strength":      "STRONG" | "MODERATE" | "WEAK",
    "ema20":         float,
    "ema50":         float,
    "ema200":        float,
    "vwap":          float,
    "adx":           float,
    "slope":         float,    # normalised EMA50 slope (-1 to +1)
    "price_vs_ema20": str,     # "ABOVE" | "BELOW"
    "price_vs_ema50": str,
    "price_vs_ema200": str,
    "price_vs_vwap":  str,
    "ema_stack":     str,      # "BULLISH" | "BEARISH" | "MIXED"
    "adx_trending":  bool,
    "confidence":    float     # 0.0 – 1.0
}

API surface
-----------
GET /api/regime  (market_context_builder includes TrendResult)
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

import numpy as np
import pandas as pd

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_EMA_SHORT  = 20
_EMA_MID    = 50
_EMA_LONG   = 200
_ADX_PERIOD = 14
_ADX_TREND_THRESHOLD = 25.0     # ADX > 25 = trending market
_ADX_STRONG_THRESHOLD = 40.0    # ADX > 40 = strong trend
_SLOPE_LOOKBACK = 10             # bars for EMA50 slope regression
_VWAP_SESSION_BARS = 96          # M15 bars in a 24-hour session


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class TrendResult:
    bias:             str   = "NEUTRAL"      # LONG_BIAS | SHORT_BIAS | NEUTRAL
    strength:         str   = "WEAK"         # STRONG | MODERATE | WEAK
    ema20:            float = 0.0
    ema50:            float = 0.0
    ema200:           float = 0.0
    vwap:             float = 0.0
    adx:              float = 0.0
    slope:            float = 0.0            # normalised −1..+1
    price_vs_ema20:   str   = ""
    price_vs_ema50:   str   = ""
    price_vs_ema200:  str   = ""
    price_vs_vwap:    str   = ""
    ema_stack:        str   = "MIXED"        # BULLISH | BEARISH | MIXED
    adx_trending:     bool  = False
    confidence:       float = 0.0

    def to_dict(self) -> dict:
        d = asdict(self)
        d["adx_trending"] = bool(d["adx_trending"])
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in d.items()}

    def is_bullish(self) -> bool:
        return self.bias == "LONG_BIAS"

    def is_bearish(self) -> bool:
        return self.bias == "SHORT_BIAS"


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class TrendEngine:
    """
    Stateless: call analyse(df) with an OHLCV DataFrame.
    Works on any timeframe; designed primarily for H4 and H1.
    """

    def __init__(self) -> None:
        logger.info("TrendEngine ready")

    # ── Public API ────────────────────────────────────────────────────────────

    def analyse(self, df: pd.DataFrame, current_price: Optional[float] = None) -> TrendResult:
        """
        Run full trend analysis on df.

        Parameters
        ----------
        df            : OHLCV DataFrame with columns open/high/low/close/volume.
                        Index should be DatetimeIndex (not required but recommended).
        current_price : override for latest price (e.g. mark price from Binance).
                        Defaults to df['close'].iloc[-1].

        Returns
        -------
        TrendResult
        """
        result = TrendResult()

        if df is None or len(df) < _EMA_SHORT + 2:
            logger.warning(f"TrendEngine: insufficient bars ({len(df) if df is not None else 0})")
            return result

        close = df["close"].astype(float)
        high  = df["high"].astype(float)
        low   = df["low"].astype(float)
        price = float(current_price) if current_price else float(close.iloc[-1])

        # ── EMAs ──────────────────────────────────────────────────────────────
        ema20  = self._ema(close, _EMA_SHORT)
        ema50  = self._ema(close, _EMA_MID)   if len(close) >= _EMA_MID   else None
        ema200 = self._ema(close, _EMA_LONG)  if len(close) >= _EMA_LONG  else None

        result.ema20  = round(ema20, 4)
        result.ema50  = round(ema50,  4) if ema50  is not None else 0.0
        result.ema200 = round(ema200, 4) if ema200 is not None else 0.0

        # ── VWAP (session) ────────────────────────────────────────────────────
        result.vwap = round(self._vwap(df, bars=_VWAP_SESSION_BARS), 4)

        # ── ADX ───────────────────────────────────────────────────────────────
        result.adx = round(self._adx(high, low, close, _ADX_PERIOD), 4)
        result.adx_trending = result.adx >= _ADX_TREND_THRESHOLD

        # ── EMA slope (normalised) ─────────────────────────────────────────
        if ema50 is not None:
            result.slope = round(self._ema_slope(close, _EMA_MID, _SLOPE_LOOKBACK), 6)

        # ── Price vs indicators ───────────────────────────────────────────────
        result.price_vs_ema20  = "ABOVE" if price > ema20  else "BELOW"
        result.price_vs_ema50  = "ABOVE" if ema50  and price > ema50  else "BELOW"
        result.price_vs_ema200 = "ABOVE" if ema200 and price > ema200 else "BELOW"
        result.price_vs_vwap   = "ABOVE" if result.vwap and price > result.vwap else "BELOW"

        # ── EMA stack ─────────────────────────────────────────────────────────
        result.ema_stack = self._ema_stack(ema20, ema50, ema200)

        # ── Bias + strength ───────────────────────────────────────────────────
        result.bias, result.strength, result.confidence = self._determine_bias(result)

        logger.debug(
            f"TrendEngine | bias={result.bias} strength={result.strength} "
            f"adx={result.adx:.1f} slope={result.slope:.5f} "
            f"stack={result.ema_stack}"
        )
        return result

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _ema(series: pd.Series, period: int) -> float:
        """Exponential moving average, last value."""
        if len(series) < period:
            return float(series.mean())
        ema_series = series.ewm(span=period, adjust=False).mean()
        val = float(ema_series.iloc[-1])
        return val if not np.isnan(val) else float(series.iloc[-1])

    @staticmethod
    def _vwap(df: pd.DataFrame, bars: int = _VWAP_SESSION_BARS) -> float:
        """Session VWAP: (typical_price × volume).cumsum / volume.cumsum over `bars`."""
        n = min(len(df), bars)
        if n < 2:
            return float(df["close"].iloc[-1]) if len(df) else 0.0
        window = df.iloc[-n:].copy()
        typical = (window["high"].astype(float) +
                   window["low"].astype(float) +
                   window["close"].astype(float)) / 3.0
        vol = window["volume"].astype(float)
        total_vol = float(vol.sum())
        if total_vol == 0 or np.isnan(total_vol):
            return float(window["close"].iloc[-1])
        vwap = float((typical * vol).sum() / total_vol)
        return vwap if not np.isnan(vwap) else float(window["close"].iloc[-1])

    @staticmethod
    def _adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int) -> float:
        """Wilder's ADX (14)."""
        if len(close) < period + 2:
            return 0.0

        # True Range
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        # Directional Movement
        up_move   = high - high.shift(1)
        down_move = low.shift(1) - low
        dm_plus  = np.where((up_move > down_move) & (up_move > 0), up_move,   0.0)
        dm_minus = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        # Smoothed (Wilder's)
        atr  = _wilder_smooth(pd.Series(tr),              period)
        dip  = _wilder_smooth(pd.Series(dm_plus,  index=tr.index), period)
        dim  = _wilder_smooth(pd.Series(dm_minus, index=tr.index), period)

        dip_pct = pd.Series(np.where(atr != 0, 100 * dip  / atr, 0.0))
        dim_pct = pd.Series(np.where(atr != 0, 100 * dim  / atr, 0.0))

        dx = pd.Series(np.where(
            (dip_pct + dim_pct) != 0,
            100 * (dip_pct - dim_pct).abs() / (dip_pct + dim_pct),
            0.0
        ))

        adx_series = _wilder_smooth(dx, period)
        val = float(adx_series.iloc[-1]) if len(adx_series) else 0.0
        return val if not np.isnan(val) else 0.0

    @staticmethod
    def _ema_slope(close: pd.Series, period: int, lookback: int) -> float:
        """
        Normalised slope of EMA(period) over last `lookback` bars.
        Returns value in roughly −1..+1 (clamped).
        """
        if len(close) < period + lookback:
            return 0.0
        ema_series = close.ewm(span=period, adjust=False).mean().iloc[-lookback:]
        if ema_series.isna().any():
            return 0.0
        vals  = ema_series.values.astype(float)
        x     = np.arange(lookback, dtype=float)
        slope = float(np.polyfit(x, vals, 1)[0])
        base  = float(np.abs(vals).mean())
        if base == 0 or np.isnan(base):
            return 0.0
        normalised = slope / base
        return float(np.clip(normalised, -1.0, 1.0))

    @staticmethod
    def _ema_stack(ema20: float, ema50: Optional[float], ema200: Optional[float]) -> str:
        """
        BULLISH : EMA20 > EMA50 > EMA200
        BEARISH : EMA20 < EMA50 < EMA200
        MIXED   : anything else
        """
        if ema50 is None or ema200 is None:
            return "MIXED"
        if ema20 > ema50 > ema200:
            return "BULLISH"
        if ema20 < ema50 < ema200:
            return "BEARISH"
        return "MIXED"

    @staticmethod
    def _determine_bias(r: TrendResult) -> tuple[str, str, float]:
        """
        Score-based bias determination.

        Signals (each = 1 point, max 6):
          +1  price above EMA20
          +1  price above EMA50
          +1  price above EMA200
          +1  price above VWAP
          +1  EMA stack BULLISH
          +1  slope > +0.0005

        Symmetrically for bearish.

        Bias:
          bull_score >= 4 → LONG_BIAS
          bear_score >= 4 → SHORT_BIAS
          else            → NEUTRAL

        Strength:
          ADX > 40 and aligned → STRONG
          ADX > 25 and aligned → MODERATE
          else                 → WEAK

        Confidence = max(bull_score, bear_score) / 6
        """
        bull, bear = 0, 0

        if r.price_vs_ema20  == "ABOVE": bull += 1
        else:                             bear += 1

        if r.price_vs_ema50  == "ABOVE": bull += 1
        else:                             bear += 1

        if r.price_vs_ema200 == "ABOVE": bull += 1
        else:                             bear += 1

        if r.price_vs_vwap   == "ABOVE": bull += 1
        else:                             bear += 1

        if r.ema_stack == "BULLISH":     bull += 1
        elif r.ema_stack == "BEARISH":   bear += 1

        if r.slope >  0.0005:            bull += 1
        elif r.slope < -0.0005:          bear += 1

        max_score = 6
        leading   = max(bull, bear)
        conf      = round(leading / max_score, 4)

        if bull >= 4:
            bias = "LONG_BIAS"
        elif bear >= 4:
            bias = "SHORT_BIAS"
        else:
            bias = "NEUTRAL"

        if r.adx >= _ADX_STRONG_THRESHOLD and bias != "NEUTRAL":
            strength = "STRONG"
        elif r.adx >= _ADX_TREND_THRESHOLD and bias != "NEUTRAL":
            strength = "MODERATE"
        else:
            strength = "WEAK"

        return bias, strength, conf


# ── Wilder smoothing helper ───────────────────────────────────────────────────

def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (equivalent to EMA with alpha=1/period)."""
    result = series.copy().astype(float)
    result.iloc[:period] = np.nan
    # Seed with simple average
    seed = float(series.iloc[:period].mean())
    result.iloc[period - 1] = seed
    alpha = 1.0 / period
    for i in range(period, len(result)):
        result.iloc[i] = result.iloc[i - 1] * (1 - alpha) + float(series.iloc[i]) * alpha
    return result
