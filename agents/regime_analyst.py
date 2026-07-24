"""
Regime Analyst Agent

Analyses market regime from RegimeEngine + TrendEngine output.
Publishes regime change events and trend bias signals.
"""

from __future__ import annotations
from events.event_bus import regime_pub
from .base_agent import BaseAgent, AgentReport


class RegimeAnalyst(BaseAgent):
    AGENT_NAME = "REGIME_ANALYST"

    def __init__(self) -> None:
        super().__init__()
        self._prev_regime: str = ""

    def analyse(self, market_context: dict) -> AgentReport:
        regime       = market_context.get("regime",       "UNKNOWN")
        regime_conf  = market_context.get("regime_conf",  0.0)
        trend_bias   = market_context.get("trend_bias",   "NEUTRAL")
        trend_str    = market_context.get("trend_strength","WEAK")
        trend_conf   = market_context.get("trend_conf",   0.0)
        mtf_aligned  = bool(market_context.get("mtf_aligned", False))
        mtf_dir      = market_context.get("mtf_direction", "")
        trend_data   = market_context.get("trend_data", {})

        # ── Regime change detection ────────────────────────────────────────
        if regime != self._prev_regime and self._prev_regime:
            regime_pub.info("REGIME_CHANGE",
                            f"Regime changed: {self._prev_regime} → {regime}",
                            {"from": self._prev_regime, "to": regime, "confidence": regime_conf})
        self._prev_regime = regime

        # ── Domain events ──────────────────────────────────────────────────
        if regime == "TREND" and regime_conf > 0.6:
            regime_pub.info("TREND_DETECTED",
                            f"Strong trend regime | bias={trend_bias} strength={trend_str}",
                            {"regime": regime, "bias": trend_bias, "confidence": regime_conf})
        elif regime in ("RANGE", "SQUEEZE"):
            regime_pub.warning("RANGE_DETECTED" if regime == "RANGE" else "SQUEEZE_WARNING",
                               f"{regime} regime — reduced position sizing recommended",
                               {"regime": regime, "confidence": regime_conf})

        # ── Signal ────────────────────────────────────────────────────────
        if regime == "TREND" and "LONG_BIAS" in trend_bias:
            signal = "LONG";  conf = min(100.0, regime_conf * 100 * (1.2 if trend_str == "STRONG" else 1.0))
        elif regime == "TREND" and "SHORT_BIAS" in trend_bias:
            signal = "SHORT"; conf = min(100.0, regime_conf * 100 * (1.2 if trend_str == "STRONG" else 1.0))
        elif regime == "VOLATILE":
            signal = "NEUTRAL"; conf = 20.0
        else:
            signal = "NEUTRAL"; conf = max(0.0, regime_conf * 50)

        ema_stack = trend_data.get("ema_stack", "")
        adx_val   = trend_data.get("adx", 0.0)
        rsi_val   = trend_data.get("rsi", 50.0)

        factors = [
            self._factor("Regime",
                         f"{regime} ({regime_conf*100:.0f}% conf)",
                         "SUPPORTS" if signal != "NEUTRAL" else "NEUTRAL",
                         f"HMM regime classification: {regime}"),
            self._factor("Trend Bias",
                         f"{trend_bias} ({trend_str})",
                         "SUPPORTS" if (signal=="LONG" and "LONG" in trend_bias) or
                                       (signal=="SHORT" and "SHORT" in trend_bias) else "NEUTRAL",
                         f"Trend confidence: {trend_conf*100:.0f}%"),
            self._factor("EMA Stack",
                         str(ema_stack),
                         "SUPPORTS" if ema_stack in ("BULLISH","BEARISH") else "NEUTRAL",
                         "EMA 20/50/200 alignment"),
            self._factor("ADX",
                         f"{adx_val:.1f}",
                         "SUPPORTS" if adx_val > 25 else "NEUTRAL",
                         "Trend strength: >25 = trending, >40 = strong"),
            self._factor("RSI",
                         f"{rsi_val:.1f}",
                         "OPPOSES" if (signal=="LONG" and rsi_val > 70) or
                                      (signal=="SHORT" and rsi_val < 30) else "NEUTRAL",
                         "Overbought > 70, Oversold < 30"),
        ]

        summary = (f"{regime} regime ({regime_conf*100:.0f}%) | "
                   f"{trend_bias} {trend_str} | {'MTF aligned' if mtf_aligned else 'MTF partial'}")

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = conf,
            summary    = summary,
            factors    = factors,
            raw        = {"regime": regime, "regime_conf": regime_conf,
                          "trend_bias": trend_bias, "trend_strength": trend_str,
                          "adx": adx_val, "rsi": rsi_val, "mtf_aligned": mtf_aligned},
        )

    def answer(self, question: str, market_context: dict | None = None) -> str:
        last = self._last
        if last is None: return "No regime analysis available yet."
        r = last.raw; q = question.lower()
        if "regime" in q:
            return (f"Current regime: {r.get('regime','?')} "
                    f"({r.get('regime_conf',0)*100:.0f}% confidence). "
                    f"This means the market is {'trending' if r.get('regime')=='TREND' else 'ranging/volatile'}.")
        if "trend" in q:
            return (f"Trend bias: {r.get('trend_bias','?')} ({r.get('trend_strength','?')}). "
                    f"ADX: {r.get('adx',0):.1f} — {'strong trend' if r.get('adx',0)>25 else 'weak trend'}.")
        if "adx" in q: return f"ADX: {r.get('adx',0):.1f}. Values >25 indicate a trend; >40 = strong."
        if "rsi" in q: return f"RSI: {r.get('rsi',50):.1f}. {'>70 = overbought' if r.get('rsi',50)>70 else '<30 = oversold' if r.get('rsi',50)<30 else 'neutral zone'}."
        return super().answer(question, market_context)
