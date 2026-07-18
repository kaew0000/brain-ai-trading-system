"""
Decision Layer: Brain Decision Engine

Scoring System (max 9 points)
──────────────────────────────
SMC  (max 4)      BOS +2 · CHOCH +1 · FVG +1 · OB +1  → capped at 4
Volume (max 2)    Spike +1 · OBV aligned +1
OI   (max 2)      Rising >1 % +2 · Rising >0 % +1
Sentiment (max 1) Balanced L/S ratio +1

Decision
────────
score ≥ 7  → TRADE  (LONG or SHORT)
score 5-6  → WAIT
score < 5  → SKIP

Hard Blocks
───────────
Funding > +0.05 %        → block LONG
Funding < -0.05 %        → block SHORT
Price ↑ + OI ↓           → Short Covering   → block LONG
Price ↓ + OI ↑           → Long Liquidation → block SHORT

Multi-Timeframe Filter
──────────────────────
H4 = Trend bias · H1 = Structure bias · M15 = Entry trigger
All three aligned → mtf_aligned=True (strongest signal)
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from features.smc_engine import SMCSignals
from features.volume_engine import VolumeSignals
from regime.regime_engine import RegimeResult
from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Result container
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DecisionResult:
    action: str = "SKIP"           # "LONG" | "SHORT" | "WAIT" | "SKIP"
    score: int = 0
    max_score: int = 9
    confidence: float = 0.0

    # Score breakdown
    smc_score: int = 0
    volume_score: int = 0
    oi_score: int = 0
    sentiment_score: int = 0

    # Hard block info
    blocked: bool = False
    block_reasons: list = field(default_factory=list)

    # Trade parameters (filled only when action is LONG / SHORT)
    direction: str = ""
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    # Context
    regime: str = ""
    mtf_aligned: bool = False
    oi_delta: float = 0.0
    funding_rate: float = 0.0

    def to_dict(self) -> dict:
        return {
            "action":          self.action,
            "score":           self.score,
            "max_score":       self.max_score,
            "confidence":      round(self.confidence, 4),
            "smc_score":       self.smc_score,
            "volume_score":    self.volume_score,
            "oi_score":        self.oi_score,
            "sentiment_score": self.sentiment_score,
            "blocked":         self.blocked,
            "block_reasons":   self.block_reasons,
            "direction":       self.direction,
            "entry_price":     round(self.entry_price, 2),
            "stop_loss":       round(self.stop_loss, 2),
            "take_profit":     round(self.take_profit, 2),
            "regime":          self.regime,
            "mtf_aligned":     self.mtf_aligned,
            "oi_delta":        round(self.oi_delta, 6),
            "funding_rate":    round(self.funding_rate, 6),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class BrainDecisionEngine:

    # ── Score constants ───────────────────────────────────────────────────
    BOS_SCORE         = 2
    CHOCH_SCORE       = 1
    FVG_SCORE         = 1
    OB_SCORE          = 1
    MAX_SMC_SCORE     = 4   # 2+1+1+1 but capped → matches total of 9

    VOL_SPIKE_SCORE   = 1
    OBV_SCORE         = 1
    MAX_VOL_SCORE     = 2

    OI_STRONG_SCORE   = 2
    OI_WEAK_SCORE     = 1
    MAX_OI_SCORE      = 2

    SENTIMENT_SCORE   = 1
    MAX_SENT_SCORE    = 1

    MAX_TOTAL         = MAX_SMC_SCORE + MAX_VOL_SCORE + MAX_OI_SCORE + MAX_SENT_SCORE  # 9

    def __init__(self) -> None:
        logger.info("BrainDecisionEngine ready")

    # ── Direction helpers ─────────────────────────────────────────────────

    @staticmethod
    def _is_bullish(bias: str) -> bool:
        return "ullish" in bias

    @staticmethod
    def _is_bearish(bias: str) -> bool:
        return "earish" in bias

    def _determine_direction(
        self,
        h4: SMCSignals,
        h1: SMCSignals,
        m15: SMCSignals,
        regime: RegimeResult,
    ) -> tuple[str, bool]:
        """
        Returns (direction, mtf_aligned).
        direction: "LONG" | "SHORT" | ""
        mtf_aligned: True only when all three timeframes fully agree.
        """
        b = self._is_bullish
        e = self._is_bearish

        bull = sum([b(h4.trend_bias), b(h1.trend_bias), b(m15.trend_bias)])
        bear = sum([e(h4.trend_bias), e(h1.trend_bias), e(m15.trend_bias)])

        if bull == 3:
            return "LONG",  True
        if bear == 3:
            return "SHORT", True

        # 2/3 aligned — accept regardless of regime (mtf_aligned=False, score will gate further)
        if bull >= 2:
            return "LONG",  False
        if bear >= 2:
            return "SHORT", False

        # M15 + H4 agreement (H1 neutral/missing)
        if b(m15.trend_bias) and b(h4.trend_bias):
            return "LONG",  False
        if e(m15.trend_bias) and e(h4.trend_bias):
            return "SHORT", False

        # M15 alone — only with trend regime to avoid noise
        if b(m15.trend_bias) and regime.regime == "TREND":
            return "LONG",  False
        if e(m15.trend_bias) and regime.regime == "TREND":
            return "SHORT", False

        return "", False

    # ── Scoring functions ─────────────────────────────────────────────────

    def _score_smc(self, entry: SMCSignals, direction: str) -> int:
        def aligned(sig_dir: str) -> bool:
            if not sig_dir:
                return True
            if direction == "LONG":
                return self._is_bullish(sig_dir)
            return self._is_bearish(sig_dir)

        raw = 0
        if entry.bos   and aligned(entry.bos_direction):   raw += self.BOS_SCORE
        if entry.choch and aligned(entry.choch_direction):  raw += self.CHOCH_SCORE
        if entry.fvg   and aligned(entry.fvg_direction):    raw += self.FVG_SCORE
        if entry.ob    and aligned(entry.ob_direction):     raw += self.OB_SCORE

        return min(raw, self.MAX_SMC_SCORE)

    def _score_volume(self, vol: VolumeSignals, direction: str) -> int:
        score = 0
        if vol.volume_spike:
            score += self.VOL_SPIKE_SCORE
        if (direction == "LONG"  and vol.obv_direction == "bullish") or \
           (direction == "SHORT" and vol.obv_direction == "bearish"):
            score += self.OBV_SCORE
        return min(score, self.MAX_VOL_SCORE)

    def _score_oi(self, oi_delta: float) -> int:
        if oi_delta > settings.OI_RISING_STRONG:
            return self.OI_STRONG_SCORE
        if oi_delta > settings.OI_RISING_WEAK:
            return self.OI_WEAK_SCORE
        return 0

    def _score_sentiment(self, ls_ratio: dict) -> int:
        ratio = float(ls_ratio.get("longShortRatio", 1.0))
        return self.SENTIMENT_SCORE if 0.80 <= ratio <= 1.20 else 0

    # ── Hard blocks ───────────────────────────────────────────────────────

    def _check_blocks(
        self,
        direction: str,
        funding: float,
        oi_delta: float,
        price_chg_pct: float,
    ) -> list[str]:
        blocks: list[str] = []

        if direction == "LONG" and funding > settings.FUNDING_BLOCK_LONG:
            blocks.append(
                f"FUNDING_BLOCK_LONG rate={funding:.5f} > {settings.FUNDING_BLOCK_LONG}"
            )
        if direction == "SHORT" and funding < settings.FUNDING_BLOCK_SHORT:
            blocks.append(
                f"FUNDING_BLOCK_SHORT rate={funding:.5f} < {settings.FUNDING_BLOCK_SHORT}"
            )
        # Short covering: price up + OI down
        if direction == "LONG" and price_chg_pct > 0 and oi_delta < -0.005:
            blocks.append(
                f"SHORT_COVERING price_chg={price_chg_pct:.4f} oi_delta={oi_delta:.4f}"
            )
        # Long liquidation: price down + OI up
        if direction == "SHORT" and price_chg_pct < 0 and oi_delta > 0.005:
            blocks.append(
                f"LONG_LIQUIDATION price_chg={price_chg_pct:.4f} oi_delta={oi_delta:.4f}"
            )
        return blocks

    # ── ATR helper ────────────────────────────────────────────────────────

    @staticmethod
    def _atr(df: pd.DataFrame, period: int = 14) -> float:
        """True-range ATR from OHLCV DataFrame."""
        if len(df) < period + 1:
            return float(df["close"].iloc[-1] * 0.005)   # 0.5 % fallback
        hl = df["high"] - df["low"]
        hc = (df["high"] - df["close"].shift(1)).abs()
        lc = (df["low"]  - df["close"].shift(1)).abs()
        tr = pd.concat([hl, hc, lc], axis=1).max(axis=1)
        return float(tr.rolling(period).mean().iloc[-1])

    # ── Stop Loss ─────────────────────────────────────────────────────────

    def _stop_loss(
        self,
        entry: SMCSignals,
        df_m15: pd.DataFrame,
        direction: str,
        price: float,
    ) -> float:
        """
        Priority:  1. Order Block  →  2. FVG / Prev H/L  →  3. ATR×1.5
        """
        max_sl_pct = 0.04   # never wider than 4 %

        # 1. Order Block
        if entry.ob and entry.ob_top > 0 and entry.ob_bottom > 0:
            if direction == "LONG":
                sl = entry.ob_bottom * (1 - 0.0005)
                if sl < price and (price - sl) / price <= max_sl_pct:
                    return round(sl, 2)
            else:
                sl = entry.ob_top * (1 + 0.0005)
                if sl > price and (sl - price) / price <= max_sl_pct:
                    return round(sl, 2)

        # 2. Previous High/Low as FVG proxy
        if direction == "LONG" and entry.prev_low > 0 and entry.prev_low < price:
            sl = entry.prev_low * (1 - 0.0005)
            if (price - sl) / price <= max_sl_pct:
                return round(sl, 2)
        if direction == "SHORT" and entry.prev_high > 0 and entry.prev_high > price:
            sl = entry.prev_high * (1 + 0.0005)
            if (sl - price) / price <= max_sl_pct:
                return round(sl, 2)

        # 3. ATR-based
        atr = self._atr(df_m15, settings.ATR_PERIOD)
        dist = atr * settings.ATR_SL_MULTIPLIER
        if direction == "LONG":
            return round(price - dist, 2)
        return round(price + dist, 2)

    # ── Take Profit ───────────────────────────────────────────────────────

    def _take_profit(
        self,
        entry: SMCSignals,
        direction: str,
        price: float,
        sl: float,
    ) -> float:
        """
        Use liquidity / prev H/L when available, else default RR 1:2.
        """
        risk = abs(price - sl)

        if direction == "LONG":
            rr_tp = price + risk * settings.DEFAULT_RR
            # Prefer nearest target above price
            candidates = []
            if entry.liquidity_high > price:
                candidates.append(entry.liquidity_high)
            if entry.prev_high > price:
                candidates.append(entry.prev_high)
            candidates = [c for c in candidates if c >= rr_tp * 0.80]
            return round(min(candidates) if candidates else rr_tp, 2)

        else:  # SHORT
            rr_tp = price - risk * settings.DEFAULT_RR
            candidates = []
            if 0 < entry.liquidity_low < price:
                candidates.append(entry.liquidity_low)
            if 0 < entry.prev_low < price:
                candidates.append(entry.prev_low)
            candidates = [c for c in candidates if c <= rr_tp * 1.20]
            return round(max(candidates) if candidates else rr_tp, 2)

    # ── Main entry ────────────────────────────────────────────────────────

    def decide(
        self,
        smc_signals: dict[str, SMCSignals],
        volume_signals: VolumeSignals,
        regime_result: RegimeResult,
        market_data: dict,
        df_m15: pd.DataFrame,
    ) -> DecisionResult:
        """
        Combine all layer signals and return a DecisionResult.

        Parameters
        ----------
        smc_signals   : {"h4": SMCSignals, "h1": SMCSignals, "m15": SMCSignals}
        volume_signals: VolumeSignals (computed on M15)
        regime_result : RegimeResult
        market_data   : dict from BinanceDataProvider.get_all_market_data()
        df_m15        : M15 OHLCV DataFrame (for SL/TP calculation)
        """
        res = DecisionResult()
        res.regime       = regime_result.regime
        res.oi_delta     = market_data.get("oi_delta", 0.0)
        res.funding_rate = market_data.get("funding_rate", 0.0)

        price = float(market_data.get("mark_price", 0.0))
        if price <= 0:
            logger.error("mark_price = 0; cannot decide")
            res.action = "SKIP"
            return res

        res.entry_price = price

        h4  = smc_signals.get("h4",  SMCSignals())
        h1  = smc_signals.get("h1",  SMCSignals())
        m15 = smc_signals.get("m15", SMCSignals())

        # ── Step 1: Direction ─────────────────────────────────────────────
        logger.info(
            f"MTF bias  | H4={h4.trend_bias!r:10} H1={h1.trend_bias!r:10} M15={m15.trend_bias!r}"
        )
        logger.info(
            f"MTF BOS   | H4={h4.bos_direction!r:10} H1={h1.bos_direction!r:10} M15={m15.bos_direction!r}"
        )
        logger.info(
            f"MTF CHOCH | H4={h4.choch_direction!r:10} H1={h1.choch_direction!r:10} M15={m15.choch_direction!r}"
        )
        direction, mtf_aligned = self._determine_direction(h4, h1, m15, regime_result)
        res.direction   = direction
        res.mtf_aligned = mtf_aligned

        if not direction:
            logger.info("No clear MTF direction → SKIP")
            res.action = "SKIP"
            return res

        # ── Step 2: Scores ────────────────────────────────────────────────
        res.smc_score       = self._score_smc(m15, direction)
        res.volume_score    = self._score_volume(volume_signals, direction)
        res.oi_score        = self._score_oi(res.oi_delta)
        res.sentiment_score = self._score_sentiment(
            market_data.get("long_short_ratio", {})
        )

        total = (res.smc_score + res.volume_score +
                 res.oi_score  + res.sentiment_score)
        res.score      = total
        res.confidence = total / self.MAX_TOTAL

        # ── Step 3: Hard blocks ───────────────────────────────────────────
        price_chg = 0.0
        if len(df_m15) >= 2:
            prev = float(df_m15["close"].iloc[-2])
            if prev > 0:
                price_chg = (price - prev) / prev

        blocks = self._check_blocks(direction, res.funding_rate, res.oi_delta, price_chg)
        if blocks:
            res.blocked      = True
            res.block_reasons = blocks
            res.action        = "SKIP"
            logger.warning(f"Trade BLOCKED: {blocks}")
            return res

        # ── Step 4: Final decision ────────────────────────────────────────
        if total >= settings.TRADE_THRESHOLD:
            res.action     = direction   # "LONG" or "SHORT"
            res.stop_loss  = self._stop_loss(m15, df_m15, direction, price)
            res.take_profit = self._take_profit(m15, direction, price, res.stop_loss)

        elif total >= settings.WAIT_THRESHOLD:
            res.action = "WAIT"

        else:
            res.action = "SKIP"

        logger.info(
            f"Decision={res.action} score={total}/{self.MAX_TOTAL} "
            f"dir={direction} MTF={mtf_aligned} regime={regime_result.regime} "
            f"[SMC={res.smc_score} VOL={res.volume_score} "
            f"OI={res.oi_score} SENT={res.sentiment_score}]"
        )
        return res
