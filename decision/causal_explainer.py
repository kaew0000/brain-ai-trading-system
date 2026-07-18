"""
Decision Layer: Causal Explainer

Produces structured JSON reasoning for every trading decision.
This is the "AI Analyst" output that powers:
  1. Dashboard Signal Panel  (reasoning display)
  2. Pixel Office NPCs       (each NPC reads its agent's factor stream)
  3. api/journal             (stored in ai_explanations table)

Output: ExplanationResult
--------------------------
{
  "direction":  "LONG" | "SHORT" | "WAIT" | "SKIP",
  "confidence": 82,
  "summary":    "Bullish BOS with rising OI and favourable funding in a trending regime.",
  "reasoning": {
    "factors": [
      {
        "agent":        "SMC_ANALYST",
        "name":         "BOS",
        "value":        "Bullish",
        "contribution": 28,          // % points contributed to confidence
        "weight":       30,          // bucket weight
        "verdict":      "SUPPORTS",  // SUPPORTS | OPPOSES | NEUTRAL
        "detail":       "Bullish Break of Structure on M15 confirms upside bias."
      },
      ...
    ],
    "hard_blocks": [
      {
        "agent":  "RISK_MANAGER",
        "reason": "FUNDING_BLOCK_LONG",
        "detail": "Funding rate 0.00062 exceeds long block threshold 0.0005"
      }
    ],
    "meta": {
      "regime":      "TREND",
      "trend_bias":  "LONG_BIAS",
      "mtf_aligned": true,
      "timestamp":   "2024-01-15T10:30:00+00:00"
    }
  }
}

Agent-to-NPC mapping (Pixel Office)
-------------------------------------
SMC_ANALYST      → structure NPC
VOLUME_ANALYST   → volume NPC
FUTURES_ANALYST  → OI/funding NPC
REGIME_ANALYST   → regime/trend NPC
RISK_MANAGER     → risk NPC
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

# ── Agent names (match event_bus.py and agent_decisions table) ─────────────────
AGENT_SMC     = "SMC_ANALYST"
AGENT_VOLUME  = "VOLUME_ANALYST"
AGENT_FUTURES = "FUTURES_ANALYST"
AGENT_REGIME  = "REGIME_ANALYST"
AGENT_RISK    = "RISK_MANAGER"


# ──────────────────────────────────────────────────────────────────────────────
# Result dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ExplanationResult:
    direction:  str  = ""
    confidence: int  = 0
    summary:    str  = ""
    reasoning:  dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "direction":  self.direction,
            "confidence": self.confidence,
            "summary":    self.summary,
            "reasoning":  self.reasoning,
        }

    def factors(self) -> list[dict]:
        return self.reasoning.get("factors", [])

    def has_blocks(self) -> bool:
        return bool(self.reasoning.get("hard_blocks"))


# ──────────────────────────────────────────────────────────────────────────────
# Engine
# ──────────────────────────────────────────────────────────────────────────────

class CausalExplainer:
    """
    Stateless. Call explain() with a ConfidenceResult and market_context.
    Returns structured JSON reasoning — never plain text.
    """

    def __init__(self) -> None:
        logger.info("CausalExplainer ready")

    # ── Public ────────────────────────────────────────────────────────────────

    def explain(
        self,
        confidence_result,          # ConfidenceResult (from confidence_engine.py)
        market_context: dict,
    ) -> ExplanationResult:
        """
        Build a full structured explanation for the given decision.

        Parameters
        ----------
        confidence_result : ConfidenceResult from ConfidenceEngine.score()
        market_context    : dict from MarketContextBuilder.build()

        Returns
        -------
        ExplanationResult
        """
        result = ExplanationResult()
        result.direction  = confidence_result.direction or confidence_result.action
        result.confidence = confidence_result.confidence

        factors     = []
        hard_blocks = []

        # ── SMC factor (agent: SMC_ANALYST) ───────────────────────────────────
        factors.extend(self._explain_smc(
            market_context,
            confidence_result.direction,
            confidence_result.breakdown.get("smc", 0),
            confidence_result.breakdown.get("smc", 0)
              / max(confidence_result.confidence, 1) * 100
              if confidence_result.confidence else 0,
        ))

        # ── Volume factor (agent: VOLUME_ANALYST) ─────────────────────────────
        factors.extend(self._explain_volume(
            market_context,
            confidence_result.direction,
            confidence_result.breakdown.get("volume", 0),
        ))

        # ── Futures factor (agent: FUTURES_ANALYST) ───────────────────────────
        factors.extend(self._explain_futures(
            market_context,
            confidence_result.direction,
            confidence_result.breakdown.get("oi", 0),
            confidence_result.breakdown.get("funding", 0),
        ))

        # ── Regime + Trend factor (agent: REGIME_ANALYST) ────────────────────
        factors.extend(self._explain_regime(
            market_context,
            confidence_result.direction,
            confidence_result.breakdown.get("regime", 0),
        ))

        # ── Hard blocks (agent: RISK_MANAGER) ─────────────────────────────────
        for reason in (confidence_result.block_reasons or []):
            hard_blocks.append(self._explain_block(reason, market_context))

        # ── Meta ──────────────────────────────────────────────────────────────
        meta = {
            "regime":      market_context.get("regime", ""),
            "trend_bias":  market_context.get("trend_bias", "NEUTRAL"),
            "mtf_aligned": bool(market_context.get("mtf_aligned", confidence_result.mtf_aligned)),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        }

        result.reasoning = {
            "factors":     factors,
            "hard_blocks": hard_blocks,
            "meta":        meta,
        }

        result.summary = self._build_summary(
            confidence_result.direction or confidence_result.action,
            confidence_result.confidence,
            factors,
            hard_blocks,
            meta,
        )

        logger.debug(
            f"CausalExplainer | dir={result.direction} conf={result.confidence}% "
            f"factors={len(factors)} blocks={len(hard_blocks)}"
        )
        return result

    # ── SMC explanation ───────────────────────────────────────────────────────

    @staticmethod
    def _explain_smc(ctx: dict, direction: str, contribution: int, weight_pct: float) -> list[dict]:
        factors = []
        smc = ctx.get("smc_m15", {})
        if not smc:
            return factors

        is_long = direction == "LONG"

        if smc.get("bos"):
            bos_dir = smc.get("bos_dir", "")
            aligned = _direction_aligned(bos_dir, is_long)
            factors.append({
                "agent":        AGENT_SMC,
                "name":         "BOS",
                "value":        bos_dir or "Detected",
                "contribution": contribution,
                "weight":       30,
                "verdict":      "SUPPORTS" if aligned else "OPPOSES",
                "detail":       (
                    f"{'Bullish' if aligned else 'Bearish'} Break of Structure on M15"
                    f" {'confirms' if aligned else 'contradicts'} {direction} bias."
                ),
            })

        if smc.get("choch"):
            choch_dir = smc.get("choch_dir", "")
            aligned = _direction_aligned(choch_dir, is_long)
            factors.append({
                "agent":        AGENT_SMC,
                "name":         "CHOCH",
                "value":        choch_dir or "Detected",
                "contribution": max(contribution - 5, 0),
                "weight":       30,
                "verdict":      "SUPPORTS" if aligned else "NEUTRAL",
                "detail":       (
                    f"Change of Character {'aligned with' if aligned else 'against'} "
                    f"{direction} — market structure shift confirmed."
                ),
            })

        if smc.get("ob"):
            ob_dir = smc.get("ob_dir", "")
            top    = smc.get("ob_top", 0.0)
            bot    = smc.get("ob_bottom", 0.0)
            aligned = _direction_aligned(ob_dir, is_long)
            factors.append({
                "agent":        AGENT_SMC,
                "name":         "ORDER_BLOCK",
                "value":        f"{ob_dir} OB {bot:.2f}–{top:.2f}",
                "contribution": max(contribution - 8, 0),
                "weight":       30,
                "verdict":      "SUPPORTS" if aligned else "NEUTRAL",
                "detail":       (
                    f"{'Bullish' if aligned else 'Bearish'} Order Block zone "
                    f"{bot:.2f}–{top:.2f}. "
                    f"{'Price entering demand zone.' if is_long else 'Price entering supply zone.'}"
                ),
            })

        if smc.get("fvg"):
            fvg_dir = smc.get("fvg_dir", "")
            aligned = _direction_aligned(fvg_dir, is_long)
            factors.append({
                "agent":        AGENT_SMC,
                "name":         "FVG",
                "value":        fvg_dir or "Detected",
                "contribution": max(contribution - 10, 0),
                "weight":       30,
                "verdict":      "SUPPORTS" if aligned else "NEUTRAL",
                "detail":       (
                    f"Fair Value Gap ({fvg_dir}) — imbalance provides "
                    f"{'entry magnet' if aligned else 'potential resistance'}."
                ),
            })

        return factors

    # ── Volume explanation ────────────────────────────────────────────────────

    @staticmethod
    def _explain_volume(ctx: dict, direction: str, contribution: int) -> list[dict]:
        vol = ctx.get("volume", {})
        if not vol:
            return []

        factors = []
        is_long = direction == "LONG"
        obv = vol.get("obv_direction", "neutral")
        obv_aligned = (is_long and obv == "bullish") or (not is_long and obv == "bearish")

        if vol.get("volume_spike"):
            ratio = vol.get("spike_ratio", 0.0)
            factors.append({
                "agent":        AGENT_VOLUME,
                "name":         "VOLUME_SPIKE",
                "value":        f"{ratio:.1f}x average",
                "contribution": contribution,
                "weight":       20,
                "verdict":      "SUPPORTS",
                "detail":       (
                    f"Volume {ratio:.1f}× above average. "
                    f"Institutional participation {'confirmed' if ratio > 2.0 else 'possible'}."
                ),
            })

        factors.append({
            "agent":        AGENT_VOLUME,
            "name":         "OBV",
            "value":        obv.capitalize(),
            "contribution": max(contribution - 8, 0),
            "weight":       20,
            "verdict":      "SUPPORTS" if obv_aligned else ("OPPOSES" if obv != "neutral" else "NEUTRAL"),
            "detail":       (
                f"On-Balance Volume trending {obv}. "
                f"{'Confirms' if obv_aligned else 'Contradicts'} {direction} thesis."
            ),
        })

        if vol.get("breakout_confirmed"):
            factors.append({
                "agent":        AGENT_VOLUME,
                "name":         "BREAKOUT_CONFIRMED",
                "value":        "True",
                "contribution": 5,
                "weight":       20,
                "verdict":      "SUPPORTS",
                "detail":       "Above-average range candle with volume spike confirms breakout momentum.",
            })

        return factors

    # ── Futures explanation ───────────────────────────────────────────────────

    @staticmethod
    def _explain_futures(
        ctx: dict, direction: str, oi_contribution: int, funding_contribution: int
    ) -> list[dict]:
        futures = ctx.get("futures", {})
        if not futures:
            return []

        factors = []
        is_long = direction == "LONG"

        # Open Interest
        oi = futures.get("open_interest", {})
        if oi:
            press   = oi.get("pressure", "NEUTRAL")
            delta   = oi.get("delta_pct", 0.0)
            aligned = (is_long and press == "BUY_PRESSURE") or \
                      (not is_long and press == "SELL_PRESSURE")
            factors.append({
                "agent":        AGENT_FUTURES,
                "name":         "OPEN_INTEREST",
                "value":        f"{oi.get('trend', 'FLAT')} ({delta:+.2%})",
                "contribution": oi_contribution,
                "weight":       20,
                "verdict":      "SUPPORTS" if aligned else ("OPPOSES" if press != "NEUTRAL" else "NEUTRAL"),
                "detail":       (
                    f"OI {oi.get('trend','FLAT')} {delta:+.2%}. "
                    f"{'Real money entering' if aligned else 'Possible unwinding'} — "
                    f"{press.replace('_',' ').lower()}."
                ),
            })

        # Funding
        fund = futures.get("funding", {})
        if fund:
            rate       = fund.get("rate", 0.0)
            bias       = fund.get("bias", "NEUTRAL")
            extreme    = bool(fund.get("extreme", False))
            annualised = fund.get("annualised", 0.0)
            favourable = (is_long and bias == "SHORT_PAYING") or \
                         (not is_long and bias == "LONG_PAYING")
            verdict = "OPPOSES" if extreme else ("SUPPORTS" if favourable else "NEUTRAL")
            factors.append({
                "agent":        AGENT_FUTURES,
                "name":         "FUNDING_RATE",
                "value":        f"{rate:.5f} ({annualised:.1f}% ann.)",
                "contribution": funding_contribution,
                "weight":       10,
                "verdict":      verdict,
                "detail":       (
                    f"Funding {rate:.5f} ({annualised:+.1f}% annualised). "
                    f"{'⚠️ EXTREME — elevated forced close risk.' if extreme else ''}"
                    f"{'Favourable: longs rewarded.' if favourable and is_long else ''}"
                    f"{'Unfavourable: longs paying shorts.' if bias=='LONG_PAYING' and is_long else ''}"
                ).strip(),
            })

        # Long/Short ratio (contrarian signal)
        ls = futures.get("long_short", {})
        if ls and ls.get("contrarian_signal") != "NONE":
            signal = ls.get("contrarian_signal", "NONE")
            verdict = "SUPPORTS" if (
                (is_long and signal == "FADE_SHORTS") or
                (not is_long and signal == "FADE_LONGS")
            ) else "NEUTRAL"
            factors.append({
                "agent":        AGENT_FUTURES,
                "name":         "LONG_SHORT_RATIO",
                "value":        f"{ls.get('ratio', 1.0):.3f} ({ls.get('crowd_bias','')})",
                "contribution": 0,
                "weight":       0,
                "verdict":      verdict,
                "detail":       (
                    f"L/S ratio {ls.get('ratio',1.0):.3f} — "
                    f"crowd is {'heavily long' if ls.get('crowd_bias')=='LONG_CROWDED' else 'heavily short'}. "
                    f"Contrarian signal: {signal.replace('_',' ').lower()}."
                ),
            })

        return factors

    # ── Regime explanation ────────────────────────────────────────────────────

    @staticmethod
    def _explain_regime(ctx: dict, direction: str, contribution: int) -> list[dict]:
        factors = []
        regime   = ctx.get("regime", "")
        trend    = ctx.get("trend_bias", "NEUTRAL")
        strength = ctx.get("trend_strength", "WEAK")
        adx      = ctx.get("trend_data", {}).get("adx", 0.0)
        is_long  = direction == "LONG"

        regime_aligned = (
            (regime == "TREND" and trend in ("LONG_BIAS", "SHORT_BIAS"))
            or regime in ("SQUEEZE",)
        )
        trend_aligned = (is_long and trend == "LONG_BIAS") or \
                        (not is_long and trend == "SHORT_BIAS")

        factors.append({
            "agent":        AGENT_REGIME,
            "name":         "MARKET_REGIME",
            "value":        f"{regime} (ADX {adx:.1f})",
            "contribution": contribution,
            "weight":       20,
            "verdict":      "SUPPORTS" if regime_aligned else "NEUTRAL",
            "detail":       (
                f"Market regime: {regime}. ADX {adx:.1f} — "
                f"{'trending market favours momentum entries.' if regime=='TREND' else ''}"
                f"{'ranging market — SMC zone reactions preferred.' if regime=='RANGE' else ''}"
                f"{'high volatility — reduce size.' if 'VOLAT' in regime else ''}"
                f"{'squeeze conditions — potential breakout imminent.' if regime=='SQUEEZE' else ''}"
            ).strip(),
        })

        factors.append({
            "agent":        AGENT_REGIME,
            "name":         "TREND_BIAS",
            "value":        f"{trend} ({strength})",
            "contribution": max(contribution - 10, 0),
            "weight":       20,
            "verdict":      "SUPPORTS" if trend_aligned else ("OPPOSES" if trend != "NEUTRAL" else "NEUTRAL"),
            "detail":       (
                f"EMA stack: {ctx.get('trend_data',{}).get('ema_stack','MIXED')}. "
                f"Trend bias: {trend} with {strength.lower()} strength. "
                f"{'Aligned with' if trend_aligned else 'Against'} {direction} direction."
            ),
        })

        return factors

    # ── Block explanation ─────────────────────────────────────────────────────

    @staticmethod
    def _explain_block(reason: str, ctx: dict) -> dict:
        details = {
            "FUTURES_BLOCK_LONG":  "FuturesIntelEngine flagged conditions that block LONG entries "
                                   "(extreme funding, short covering, or long squeeze detected).",
            "FUTURES_BLOCK_SHORT": "FuturesIntelEngine flagged conditions that block SHORT entries "
                                   "(extreme inverse funding, long liquidation, or short squeeze).",
        }
        if reason.startswith("FUNDING_BLOCK"):
            rate   = float(ctx.get("funding_rate", 0.0))
            detail = f"Funding rate {rate:.5f} exceeds the block threshold for this direction."
        elif reason.startswith("SHORT_COVERING"):
            detail = "Price rising while OI falling — short covering, not organic buying."
        elif reason.startswith("LONG_LIQUIDATION"):
            detail = "Price falling while OI rising — long positions being liquidated."
        else:
            detail = details.get(reason, f"Hard block: {reason}")

        return {
            "agent":  AGENT_RISK,
            "reason": reason,
            "detail": detail,
        }

    # ── Summary builder ───────────────────────────────────────────────────────

    @staticmethod
    def _build_summary(
        direction: str,
        confidence: int,
        factors: list[dict],
        hard_blocks: list[dict],
        meta: dict,
    ) -> str:
        """
        Build a concise natural-language summary from the structured factors.
        Used as the dashboard Signal Panel headline and NPC speech trigger.
        """
        if hard_blocks:
            block_names = ", ".join(b["reason"] for b in hard_blocks)
            return f"Trade BLOCKED: {block_names}. No entry despite {confidence}% confidence."

        if direction in ("SKIP", "WAIT", ""):
            return f"No trade setup — confidence {confidence}% below threshold."

        supports = [f["name"] for f in factors if f["verdict"] == "SUPPORTS"]
        opposes  = [f["name"] for f in factors if f["verdict"] == "OPPOSES"]
        regime   = meta.get("regime", "")
        trend    = meta.get("trend_bias", "")
        mtf      = meta.get("mtf_aligned", False)

        parts = [f"{direction} setup | {confidence}% confidence."]

        if supports:
            parts.append(f"Supporting: {', '.join(supports[:3])}.")

        if opposes:
            parts.append(f"Against: {', '.join(opposes[:2])}.")

        if regime:
            parts.append(f"Regime: {regime}.")

        if mtf:
            parts.append("All timeframes aligned.")

        return " ".join(parts)


# ── Helper ────────────────────────────────────────────────────────────────────

def _direction_aligned(signal_dir: str, is_long: bool) -> bool:
    if not signal_dir:
        return True   # unknown = don't penalise
    bullish = "ullish" in signal_dir or "Long" in signal_dir
    return bullish == is_long
