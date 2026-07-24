"""
Decision Layer: Confidence Engine

Replaces the legacy 9-point integer score with a weighted 0–100%
confidence output and a full per-category breakdown.

Default weights (configurable via config profile)
-------------------------------------------------
smc      : 30%   (BOS/CHOCH/FVG/OB — structure)
volume   : 20%   (spike + OBV — confirmation)
oi       : 20%   (open interest trend — smart money)
funding  : 10%   (funding rate — market structure)
regime   : 20%   (market regime alignment)

Total    : 100%

Weights are intentionally sum-to-100 so the output is directly readable
as a percentage. Individual weights can be overridden at runtime via
a config profile.

Hard blocks (override regardless of score)
------------------------------------------
Implemented as a pre-filter in `gate()`. When a hard block fires, the
confidence is preserved (useful for display) but `action` is forced to
"BLOCKED". The dashboard Signal Panel shows the block reason alongside
the underlying confidence.

Output: ConfidenceResult
------------------------
{
  "action":      "LONG" | "SHORT" | "WAIT" | "SKIP" | "BLOCKED",
  "direction":   "LONG" | "SHORT" | "",
  "confidence":  82,        # integer 0-100
  "breakdown": {
      "smc":     30,        # points earned from SMC weight bucket
      "volume":  15,
      "oi":      20,
      "funding":  7,
      "regime":  10
  },
  "blocked":     false,
  "block_reasons": [],
  "entry_price": float,
  "stop_loss":   float,
  "take_profit": float,
  "mtf_aligned": bool,
  "regime":      str
}

API surface: /api/decision  /api/signals
"""

from __future__ import annotations

from dataclasses import dataclass, field

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Default weights (must sum to 100) ─────────────────────────────────────────
DEFAULT_WEIGHTS: dict[str, float] = {
    "smc":     30.0,
    "volume":  20.0,
    "oi":      20.0,
    "funding": 10.0,
    "regime":  20.0,
}

# ── Action thresholds ─────────────────────────────────────────────────────────
TRADE_THRESHOLD = 75     # confidence >= 75 → enter trade
WAIT_THRESHOLD  = 50     # confidence >= 50 → wait (no entry, no skip)


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ConfidenceResult:
    action:        str   = "SKIP"
    direction:     str   = ""
    confidence:    int   = 0          # 0-100 integer
    breakdown:     dict  = field(default_factory=dict)

    blocked:       bool  = False
    block_reasons: list  = field(default_factory=list)

    entry_price:   float = 0.0
    stop_loss:     float = 0.0
    take_profit:   float = 0.0
    mtf_aligned:   bool  = False
    regime:        str   = ""

    # Carry forward raw score for backward compat with v1 journal
    raw_score:     int   = 0
    max_score:     int   = 9

    # Futures context — populated by ConfidenceEngine.score() from market_context
    oi_delta:      float = 0.0
    funding_rate:  float = 0.0

    # Alias so TradeRecord.from_decision() works with either result type
    @property
    def score(self) -> int:
        return self.raw_score

    def to_dict(self) -> dict:
        return {
            "action":        self.action,
            "direction":     self.direction,
            "confidence":    self.confidence,
            "breakdown":     self.breakdown,
            "blocked":       self.blocked,
            "block_reasons": self.block_reasons,
            "entry_price":   round(self.entry_price,   2),
            "stop_loss":     round(self.stop_loss,     2),
            "take_profit":   round(self.take_profit,   2),
            "mtf_aligned":   self.mtf_aligned,
            "regime":        self.regime,
            "raw_score":     self.raw_score,
            "max_score":     self.max_score,
            "oi_delta":      round(self.oi_delta,     6),
            "funding_rate":  round(self.funding_rate, 6),
        }


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class ConfidenceEngine:
    """
    Converts raw engine outputs into a weighted confidence score.

    Accepts both new (market_context dict from MarketContextBuilder) and
    legacy (DecisionResult from BrainDecisionEngine) inputs so it can be
    inserted into the V1 pipeline without breaking existing tests.
    """

    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = _normalise_weights(weights or DEFAULT_WEIGHTS)
        logger.info(f"ConfidenceEngine ready | weights={self._weights}")

    # ── Public ────────────────────────────────────────────────────────────────

    def score(
        self,
        market_context: dict,
        direction: str,
        entry_price: float = 0.0,
        stop_loss:   float = 0.0,
        take_profit: float = 0.0,
        mtf_aligned: bool  = False,
    ) -> ConfidenceResult:
        """
        Compute a ConfidenceResult from market_context (MarketContextBuilder output).

        Parameters
        ----------
        market_context : full context dict from MarketContextBuilder.build()
        direction      : "LONG" | "SHORT" | "" (empty = no direction)
        """
        result = ConfidenceResult()
        result.direction   = direction
        result.regime      = market_context.get("regime", "")
        result.mtf_aligned = bool(market_context.get("mtf_aligned", mtf_aligned))
        result.entry_price = entry_price
        result.stop_loss   = stop_loss
        result.take_profit = take_profit

        if not direction:
            result.action = "SKIP"
            return result

        # ── Category scores (0.0 – 1.0 each) ─────────────────────────────────
        smc_raw     = self._score_smc(market_context, direction)
        volume_raw  = self._score_volume(market_context, direction)
        oi_raw      = self._score_oi(market_context)
        funding_raw = self._score_funding(market_context, direction)
        regime_raw  = self._score_regime(market_context, direction)

        # ── Apply weights → breakdown (integer points per category) ───────────
        w = self._weights
        breakdown = {
            "smc":     _pct(smc_raw     * w["smc"]),
            "volume":  _pct(volume_raw  * w["volume"]),
            "oi":      _pct(oi_raw      * w["oi"]),
            "funding": _pct(funding_raw * w["funding"]),
            "regime":  _pct(regime_raw  * w["regime"]),
        }

        total_confidence = sum(breakdown.values())

        result.breakdown  = breakdown
        result.confidence = min(int(round(total_confidence)), 100)

        # ── Carry forward raw score (v1 compat: 0-9) ─────────────────────────
        result.raw_score = _to_raw_score(smc_raw, volume_raw, oi_raw)
        result.max_score = 9

        # ── Futures context fields (used by TradeRecord.from_decision) ────────
        result.oi_delta     = float(market_context.get("oi_delta",     0.0))
        result.funding_rate = float(market_context.get("funding_rate", 0.0))

        # ── Hard blocks ───────────────────────────────────────────────────────
        blocks = self._check_blocks(market_context, direction)
        if blocks:
            result.blocked      = True
            result.block_reasons = blocks
            result.action       = "BLOCKED"
            logger.warning(f"ConfidenceEngine: BLOCKED {blocks}")
            return result

        # ── Action ────────────────────────────────────────────────────────────
        if result.confidence >= TRADE_THRESHOLD:
            result.action = direction   # "LONG" or "SHORT"
        elif result.confidence >= WAIT_THRESHOLD:
            result.action = "WAIT"
        else:
            result.action = "SKIP"

        logger.info(
            f"Confidence | dir={direction} total={result.confidence}% "
            f"smc={breakdown['smc']} vol={breakdown['volume']} "
            f"oi={breakdown['oi']} fund={breakdown['funding']} "
            f"regime={breakdown['regime']} → {result.action}"
        )
        return result

    # ── Backward compat: score from legacy DecisionResult dict ───────────────

    def score_from_decision(self, decision_dict: dict) -> ConfidenceResult:
        """
        Wrap a v1 DecisionResult.to_dict() into a ConfidenceResult.
        Used so existing execution code can consume ConfidenceResult
        without immediately migrating to full market_context pipeline.
        """
        result = ConfidenceResult()
        result.direction   = decision_dict.get("direction", "")
        result.regime      = decision_dict.get("regime", "")
        result.mtf_aligned = bool(decision_dict.get("mtf_aligned", False))
        result.entry_price = float(decision_dict.get("entry_price", 0.0))
        result.stop_loss   = float(decision_dict.get("stop_loss",   0.0))
        result.take_profit = float(decision_dict.get("take_profit", 0.0))
        result.blocked     = bool(decision_dict.get("blocked", False))
        result.block_reasons = decision_dict.get("block_reasons", [])
        result.raw_score   = int(decision_dict.get("score", 0))
        result.max_score   = int(decision_dict.get("max_score", 9))

        # Map per-category scores to weighted breakdown
        smc_r  = decision_dict.get("smc_score",       0) / 4.0
        vol_r  = decision_dict.get("volume_score",     0) / 2.0
        oi_r   = decision_dict.get("oi_score",         0) / 2.0
        sent_r = decision_dict.get("sentiment_score",  0) / 1.0

        w = self._weights
        # sentiment_score → funding bucket (closest semantic match)
        breakdown = {
            "smc":     _pct(smc_r  * w["smc"]),
            "volume":  _pct(vol_r  * w["volume"]),
            "oi":      _pct(oi_r   * w["oi"]),
            "funding": _pct(sent_r * w["funding"]),
            "regime":  0,   # v1 didn't separate regime
        }
        result.breakdown  = breakdown
        result.confidence = min(int(round(sum(breakdown.values()))), 100)

        if result.blocked:
            result.action = "BLOCKED"
        elif result.confidence >= TRADE_THRESHOLD:
            result.action = result.direction or "SKIP"
        elif result.confidence >= WAIT_THRESHOLD:
            result.action = "WAIT"
        else:
            result.action = "SKIP"

        return result

    # ── Category scorers (all return 0.0 – 1.0) ──────────────────────────────

    @staticmethod
    def _score_smc(ctx: dict, direction: str) -> float:
        """Score SMC signals from M15 context."""
        smc = ctx.get("smc_m15", {})
        if not smc:
            return 0.0

        score = 0
        is_long = direction == "LONG"

        bos_dir = smc.get("bos_dir", "")
        choch_dir = smc.get("choch_dir", "")
        fvg_dir  = smc.get("fvg_dir", "")
        ob_dir   = smc.get("ob_dir", "")

        def aligned(d: str) -> bool:
            if not d: return True
            return ("ullish" in d) == is_long

        if smc.get("bos")   and aligned(bos_dir):   score += 2  # max 2
        if smc.get("choch") and aligned(choch_dir):  score += 1
        if smc.get("fvg")   and aligned(fvg_dir):    score += 1
        if smc.get("ob")    and aligned(ob_dir):     score += 1

        return min(score / 4.0, 1.0)   # normalise: max raw = 5, cap at 4

    @staticmethod
    def _score_volume(ctx: dict, direction: str) -> float:
        vol = ctx.get("volume", {})
        if not vol:
            return 0.0
        score = 0
        if vol.get("volume_spike"):
            score += 1
        obv = vol.get("obv_direction", "")
        if (direction == "LONG"  and obv == "bullish") or \
           (direction == "SHORT" and obv == "bearish"):
            score += 1
        if vol.get("breakout_confirmed"):
            score += 1
        return min(score / 2.0, 1.0)   # max meaningful = 2, breakout is bonus

    @staticmethod
    def _score_oi(ctx: dict) -> float:
        futures = ctx.get("futures", {})
        if not futures:
            # Fallback: raw oi_delta
            delta = float(ctx.get("oi_delta", 0.0))
            if delta > settings.OI_RISING_STRONG: return 1.0
            if delta > settings.OI_RISING_WEAK:   return 0.5
            return 0.0

        oi  = futures.get("open_interest", {})
        press = oi.get("pressure", "NEUTRAL")
        delta = float(oi.get("delta_pct", 0.0))

        if press == "BUY_PRESSURE":
            return 1.0 if delta > settings.OI_RISING_STRONG else 0.6
        if press == "SELL_PRESSURE":
            return 0.0
        return 0.3   # FLAT = slight positive (OI stable)

    @staticmethod
    def _score_funding(ctx: dict, direction: str) -> float:
        futures = ctx.get("futures", {})
        if not futures:
            rate = float(ctx.get("funding_rate", 0.0))
            # Extreme funding → 0; normal → 0.5; favourable → 1.0
            if abs(rate) >= 0.0005:
                return 0.0
            return 0.5

        fund = futures.get("funding", {})
        bias = fund.get("bias", "NEUTRAL")
        extreme = bool(fund.get("extreme", False))

        if extreme:
            return 0.0

        # SHORT_PAYING → shorts paying longs → bullish pressure
        if direction == "LONG" and bias == "SHORT_PAYING":  return 1.0
        if direction == "SHORT" and bias == "LONG_PAYING":  return 1.0
        if bias == "NEUTRAL":                               return 0.7
        return 0.3   # paying against direction = slight negative

    @staticmethod
    def _score_regime(ctx: dict, direction: str) -> float:
        regime   = ctx.get("regime", "")
        trend    = ctx.get("trend_bias", "NEUTRAL")
        strength = ctx.get("trend_strength", "WEAK")

        score = 0.0

        # Regime alignment
        if regime == "TREND":
            score += 0.6
            if strength == "STRONG":   score += 0.3
            elif strength == "MODERATE": score += 0.15
        elif regime == "RANGE":
            # SMC/mean-reversion setups work in range — partial credit
            score += 0.4
        elif regime in ("HIGH_VOLATILITY", "VOLATILE"):
            score += 0.2   # risky; reduced credit
        elif regime == "SQUEEZE":
            score += 0.3   # potential breakout

        # Trend bias alignment with direction
        if direction == "LONG"  and trend == "LONG_BIAS":  score += 0.1
        if direction == "SHORT" and trend == "SHORT_BIAS": score += 0.1

        return min(score, 1.0)

    # ── Hard blocks ───────────────────────────────────────────────────────────

    @staticmethod
    def _check_blocks(ctx: dict, direction: str) -> list[str]:
        blocks: list[str] = []

        # Use pre-computed flags from MarketContextBuilder
        if direction == "LONG"  and ctx.get("blocks_long"):
            blocks.append("FUTURES_BLOCK_LONG")
        if direction == "SHORT" and ctx.get("blocks_short"):
            blocks.append("FUTURES_BLOCK_SHORT")

        # Legacy funding gate (matches v1 settings)
        rate = float(ctx.get("funding_rate", 0.0))
        if direction == "LONG"  and rate > settings.FUNDING_BLOCK_LONG:
            blocks.append(f"FUNDING_BLOCK_LONG rate={rate:.5f}")
        if direction == "SHORT" and rate < settings.FUNDING_BLOCK_SHORT:
            blocks.append(f"FUNDING_BLOCK_SHORT rate={rate:.5f}")

        return blocks

    # ── Weight management ─────────────────────────────────────────────────────

    def update_weights(self, new_weights: dict[str, float]) -> None:
        """Update category weights at runtime (called by config profile loader)."""
        self._weights = _normalise_weights(new_weights)
        logger.info(f"ConfidenceEngine weights updated: {self._weights}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _normalise_weights(w: dict[str, float]) -> dict[str, float]:
    """Normalise weights to sum to 100.0."""
    total = sum(w.values())
    if total == 0:
        return dict(DEFAULT_WEIGHTS)
    return {k: round(v / total * 100, 4) for k, v in w.items()}


def _pct(value: float) -> int:
    """Round a weighted float to nearest integer percentage point."""
    return int(round(value))


def _to_raw_score(smc: float, vol: float, oi: float) -> int:
    """Convert fractional sub-scores back to v1 integer score (0-9)."""
    return int(round(smc * 4 + vol * 2 + oi * 2))
