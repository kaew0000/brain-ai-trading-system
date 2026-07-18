"""
Feature Layer: Volume Engine
Logic based on harshgupta1810/volume_analysis_stockmarket.

Computes:
  - Volume Spike  (current vol vs N-bar average)
  - OBV Direction (slope of On-Balance Volume)
  - Volume Divergence (price vs OBV divergence)
  - Breakout Confirmation (large range + spike)
  - Score  0-2  (used by BrainDecisionEngine)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Data container
# ──────────────────────────────────────────────────────────────────────────────

class VolumeSignals:
    """All volume-based signals for one OHLCV timeframe."""

    __slots__ = (
        "volume_spike", "obv_direction",
        "divergence", "divergence_type",
        "breakout_confirmed",
        "score",
        "avg_volume", "current_volume", "volume_ratio",
    )

    def __init__(self) -> None:
        self.volume_spike: bool = False
        self.obv_direction: str = "neutral"   # "bullish" | "bearish" | "neutral"
        self.divergence: bool = False
        self.divergence_type: str = ""        # "bullish_divergence" | "bearish_divergence"
        self.breakout_confirmed: bool = False
        self.score: int = 0
        self.avg_volume: float = 0.0
        self.current_volume: float = 0.0
        self.volume_ratio: float = 0.0

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__slots__}


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class VolumeEngine:
    """
    Stateless volume analysis engine.

    Parameters
    ----------
    spike_multiplier : float
        Volume is a spike when current_vol > avg_vol * spike_multiplier.
    avg_period : int
        Rolling window for average volume baseline.
    """

    def __init__(
        self,
        spike_multiplier: float | None = None,
        avg_period: int | None = None,
    ) -> None:
        self.spike_multiplier = spike_multiplier or settings.VOLUME_SPIKE_MULTIPLIER
        self.avg_period       = avg_period       or settings.VOLUME_AVG_PERIOD
        logger.info(
            f"VolumeEngine | spike_multiplier={self.spike_multiplier} "
            f"avg_period={self.avg_period}"
        )

    # ── OBV ──────────────────────────────────────────────────────────────

    @staticmethod
    def _compute_obv(df: pd.DataFrame) -> pd.Series:
        closes  = df["close"].values.astype(float)
        volumes = df["volume"].values.astype(float)
        obv = np.empty(len(df))
        obv[0] = 0.0
        for i in range(1, len(df)):
            if closes[i] > closes[i - 1]:
                obv[i] = obv[i - 1] + volumes[i]
            elif closes[i] < closes[i - 1]:
                obv[i] = obv[i - 1] - volumes[i]
            else:
                obv[i] = obv[i - 1]
        return pd.Series(obv, index=df.index)

    def _obv_direction(self, obv: pd.Series, lookback: int = 8) -> str:
        """Direction from linear regression slope of recent OBV."""
        if len(obv) < lookback + 1:
            return "neutral"
        recent = obv.iloc[-lookback:].values
        if np.isnan(recent).any():
            logger.warning("VolumeEngine: OBV window contains NaN — returning neutral")
            return "neutral"
        x = np.arange(lookback, dtype=float)
        slope = float(np.polyfit(x, recent, 1)[0])
        magnitude = float(np.abs(recent).mean())
        if magnitude == 0 or pd.isna(magnitude):
            return "neutral"
        norm = slope / magnitude
        if pd.isna(norm):
            return "neutral"
        if norm > 0.001:
            return "bullish"
        if norm < -0.001:
            return "bearish"
        return "neutral"

    # ── Volume spike ─────────────────────────────────────────────────────

    def _volume_spike(
        self, df: pd.DataFrame
    ) -> tuple[bool, float, float, float]:
        """Returns (is_spike, current_vol, avg_vol, ratio)."""
        if len(df) < self.avg_period + 1:
            return False, 0.0, 0.0, 0.0
        baseline = df["volume"].iloc[-(self.avg_period + 1):-1]
        avg  = float(baseline.mean())
        cur  = float(df["volume"].iloc[-1])
        if avg == 0:
            return False, cur, avg, 0.0
        ratio = cur / avg
        return ratio >= self.spike_multiplier, cur, avg, ratio

    # ── Divergence ───────────────────────────────────────────────────────

    def _detect_divergence(
        self,
        df: pd.DataFrame,
        obv: pd.Series,
        lookback: int = 14,
    ) -> tuple[bool, str]:
        """
        Classic price–OBV divergence over the last `lookback` bars,
        split into two equal halves.
        """
        if len(df) < lookback * 2:
            return False, ""

        half = lookback // 2
        c = df["close"].iloc[-lookback:]
        o = obv.iloc[-lookback:]

        # first half vs second half extremes
        p_lo1 = float(c.iloc[:half].min());  p_lo2 = float(c.iloc[half:].min())
        p_hi1 = float(c.iloc[:half].max());  p_hi2 = float(c.iloc[half:].max())
        o_lo1 = float(o.iloc[:half].min());  o_lo2 = float(o.iloc[half:].min())
        o_hi1 = float(o.iloc[:half].max());  o_hi2 = float(o.iloc[half:].max())

        # Bullish divergence: price lower low, OBV higher low
        if p_lo2 < p_lo1 and o_lo2 > o_lo1:
            return True, "bullish_divergence"

        # Bearish divergence: price higher high, OBV lower high
        if p_hi2 > p_hi1 and o_hi2 < o_hi1:
            return True, "bearish_divergence"

        return False, ""

    # ── Breakout confirmation ─────────────────────────────────────────────

    def _breakout_confirmed(self, df: pd.DataFrame) -> bool:
        """True when latest candle has above-average range AND volume spike."""
        if len(df) < 20:
            return False
        tr = pd.concat(
            [
                df["high"] - df["low"],
                (df["high"] - df["close"].shift(1)).abs(),
                (df["low"]  - df["close"].shift(1)).abs(),
            ],
            axis=1,
        ).max(axis=1)
        atr = float(tr.rolling(14).mean().iloc[-1])
        if pd.isna(atr):
            logger.warning("VolumeEngine: ATR is NaN (insufficient valid bars) — skipping breakout check")
            return False
        last_range = float(df["high"].iloc[-1] - df["low"].iloc[-1])
        if pd.isna(last_range):
            logger.warning("VolumeEngine: last_range is NaN — skipping breakout check")
            return False
        is_spike, *_ = self._volume_spike(df)
        return (last_range > 1.5 * atr) and is_spike

    # ── Score ─────────────────────────────────────────────────────────────

    def _compute_score(
        self,
        is_spike: bool,
        obv_dir: str,
        direction_hint: str,
    ) -> int:
        """
        Max 2.
        +1 volume spike
        +1 OBV aligned with direction_hint (or any non-neutral if no hint)
        """
        score = 0
        if is_spike:
            score += 1
        if direction_hint:
            aligned = (direction_hint == "LONG" and obv_dir == "bullish") or \
                      (direction_hint == "SHORT" and obv_dir == "bearish")
            if aligned:
                score += 1
        else:
            if obv_dir in ("bullish", "bearish"):
                score += 1
        return score

    # ── Public API ────────────────────────────────────────────────────────

    def analyze(
        self,
        df: pd.DataFrame,
        direction_hint: str = "",
    ) -> VolumeSignals:
        """
        Full volume analysis.

        Parameters
        ----------
        df : OHLCV DataFrame
        direction_hint : "LONG" | "SHORT" | ""
            When provided, OBV alignment scoring uses this direction.

        Returns
        -------
        VolumeSignals
        """
        sig = VolumeSignals()
        min_bars = max(self.avg_period + 5, 30)

        try:
            if len(df) < min_bars:
                logger.warning(f"VolumeEngine: insufficient bars ({len(df)} < {min_bars})")
                return sig

            df = df.copy()

            obv = self._compute_obv(df)

            is_spike, cur, avg, ratio = self._volume_spike(df)
            sig.volume_spike   = is_spike
            sig.current_volume = cur
            sig.avg_volume     = avg
            sig.volume_ratio   = round(ratio, 3)

            sig.obv_direction = self._obv_direction(obv)

            has_div, div_type = self._detect_divergence(df, obv)
            sig.divergence      = has_div
            sig.divergence_type = div_type

            sig.breakout_confirmed = self._breakout_confirmed(df)
            sig.score = self._compute_score(is_spike, sig.obv_direction, direction_hint)

            logger.debug(
                f"Volume spike={sig.volume_spike}(×{ratio:.2f}) "
                f"OBV={sig.obv_direction} "
                f"div={sig.divergence}({sig.divergence_type}) "
                f"score={sig.score}"
            )

        except Exception as exc:
            logger.error(f"VolumeEngine error: {exc}", exc_info=True)

        return sig
