"""
Futures Analyst Agent

Analyses futures-specific data from the FuturesIntelEngine:
  - Open Interest (rising/falling × price direction)
  - Funding Rate (long crowded / short crowded / extreme)
  - Liquidation events (cascade detection)
  - Long/Short ratio (crowd sentiment + contrarian signals)
  - Taker buy/sell ratio (aggressor dominance)

Publishes specific events to EventBus:
  OI_RISING_PRICE_RISING, OI_RISING_PRICE_FALLING,
  FUNDING_EXTREME_LONG, FUNDING_EXTREME_SHORT,
  LONG_LIQUIDATION_CASCADE, SHORT_LIQUIDATION_CASCADE,
  LONG_CROWDED, SHORT_CROWDED
"""

from __future__ import annotations


from events.event_bus import futures_pub
from .base_agent import BaseAgent, AgentReport


class FuturesAnalyst(BaseAgent):
    """AI employee responsible for futures market intelligence."""

    AGENT_NAME = "FUTURES_ANALYST"

    def analyse(self, market_context: dict) -> AgentReport:
        fut = market_context.get("futures", {})
        funding_data  = fut.get("funding", {})
        oi_data       = fut.get("open_interest", {})
        ls_data       = fut.get("long_short", {})
        taker_data    = fut.get("taker", {})
        liq_data      = fut.get("liquidation", {})

        # ── Raw values ─────────────────────────────────────────────────────
        funding_rate  = funding_data.get("rate", 0.0) or market_context.get("funding_rate", 0.0)
        funding_ann   = funding_data.get("annualised", 0.0)
        funding_ext   = bool(funding_data.get("extreme", False))
        funding_bias  = funding_data.get("bias", "NEUTRAL")

        oi_delta      = oi_data.get("delta_pct", 0.0) or market_context.get("oi_delta", 0.0)
        oi_trend      = oi_data.get("trend", "FLAT")
        oi_pressure   = oi_data.get("pressure", "NEUTRAL")

        ls_ratio      = ls_data.get("ratio", 1.0)
        ls_crowd      = ls_data.get("crowd_bias", "NEUTRAL")
        ls_contrarian = ls_data.get("contrarian_signal", "NEUTRAL")

        taker_agg     = taker_data.get("aggressor", "BALANCED")
        taker_buy     = taker_data.get("buy_ratio", 0.5)

        liq_detected  = bool(liq_data.get("detected", False))
        liq_type      = liq_data.get("type", "")
        liq_severity  = liq_data.get("severity", "LOW")

        mark_price    = market_context.get("mark_price", 0.0)

        # ── OI × Price divergence analysis ────────────────────────────────
        oi_scenario = self._classify_oi(oi_trend, oi_delta, mark_price)

        # ── EventBus publish ───────────────────────────────────────────────
        if oi_trend == "RISING" and oi_delta > 0.005:
            futures_pub.info("OI_RISING",
                             f"OI rising +{oi_delta*100:.2f}% — {oi_scenario}",
                             {"oi_delta": oi_delta, "scenario": oi_scenario})

        if funding_ext:
            bias = funding_data.get("bias", "")
            event = "FUNDING_EXTREME_LONG" if "LONG" in bias else "FUNDING_EXTREME_SHORT"
            futures_pub.warning(event,
                                f"Extreme funding {funding_rate*100:.4f}% — {bias} paying",
                                {"rate": funding_rate, "annualised": funding_ann, "bias": bias})
        elif abs(funding_rate) > 0.0002:
            futures_pub.info("FUNDING_ELEVATED",
                             f"Funding {funding_rate*100:.4f}% — {funding_bias}",
                             {"rate": funding_rate, "bias": funding_bias})

        if ls_ratio > 1.5:
            futures_pub.warning("LONG_CROWDED",
                                f"Long/Short ratio {ls_ratio:.2f} — longs crowded, contrarian SHORT bias",
                                {"ratio": ls_ratio, "contrarian": ls_contrarian})
        elif ls_ratio < 0.7:
            futures_pub.warning("SHORT_CROWDED",
                                f"Long/Short ratio {ls_ratio:.2f} — shorts crowded, contrarian LONG bias",
                                {"ratio": ls_ratio, "contrarian": ls_contrarian})

        if liq_detected:
            event = "LONG_LIQUIDATION_CASCADE" if "LONG" in liq_type else "SHORT_LIQUIDATION_CASCADE"
            severity = liq_severity
            futures_pub.warning(event,
                                f"{liq_type} liquidation cascade — severity: {severity}",
                                {"type": liq_type, "severity": severity})

        # ── Signal determination ───────────────────────────────────────────
        signal, confidence, summary = self._determine_signal(
            oi_trend, oi_delta, oi_scenario,
            funding_rate, funding_ext, funding_bias,
            ls_ratio, ls_contrarian,
            taker_agg, taker_buy,
            liq_detected, liq_type,
        )

        factors = [
            self._factor("OI Trend",
                         f"{oi_trend} {oi_delta*100:+.2f}%",
                         self._oi_verdict(oi_trend, oi_delta, signal),
                         f"Scenario: {oi_scenario}"),
            self._factor("Funding Rate",
                         f"{funding_rate*100:.4f}% ({'EXTREME' if funding_ext else 'normal'})",
                         self._funding_verdict(funding_rate, funding_ext, signal),
                         f"Annualised: {funding_ann:.1f}% | Bias: {funding_bias}"),
            self._factor("Long/Short Ratio",
                         f"{ls_ratio:.2f} ({ls_crowd})",
                         self._ls_verdict(ls_ratio, ls_contrarian, signal),
                         f"Contrarian signal: {ls_contrarian}"),
            self._factor("Taker Side",
                         f"{taker_agg} (buy={taker_buy*100:.0f}%)",
                         "SUPPORTS" if (signal == "LONG" and taker_buy > 0.55) or
                                       (signal == "SHORT" and taker_buy < 0.45) else "NEUTRAL",
                         f"Aggressor: {taker_agg}"),
            self._factor("Liquidation",
                         f"{liq_type} {liq_severity}" if liq_detected else "None detected",
                         self._liq_verdict(liq_detected, liq_type, signal),
                         "Cascade event detected" if liq_detected else "No liquidation cascade"),
        ]

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = confidence,
            summary    = summary,
            factors    = factors,
            raw        = {
                "funding_rate":    funding_rate,
                "funding_extreme": funding_ext,
                "funding_bias":    funding_bias,
                "oi_delta":        oi_delta,
                "oi_trend":        oi_trend,
                "oi_scenario":     oi_scenario,
                "ls_ratio":        ls_ratio,
                "ls_crowd":        ls_crowd,
                "ls_contrarian":   ls_contrarian,
                "taker_aggressor": taker_agg,
                "liq_detected":    liq_detected,
                "liq_type":        liq_type,
                "mark_price":      mark_price,
            },
        )

    def answer(self, question: str, market_context: dict | None = None) -> str:
        last = self._last
        if last is None:
            return "No futures analysis available yet."

        r = last.raw
        q = question.lower()

        if "funding" in q:
            rate = r.get("funding_rate", 0)
            bias = r.get("funding_bias", "NEUTRAL")
            ext  = r.get("funding_extreme", False)
            status = "EXTREME — trade risk elevated" if ext else "normal range"
            return (f"Funding rate: {rate*100:.4f}% ({status}). "
                    f"Bias: {bias}. "
                    f"{'Longs are paying shorts.' if 'LONG' in bias else 'Shorts are paying longs.' if 'SHORT' in bias else 'Rate is balanced.'}")

        if "oi" in q or "open interest" in q:
            oi    = r.get("oi_delta", 0)
            trend = r.get("oi_trend", "FLAT")
            scene = r.get("oi_scenario", "")
            return (f"Open Interest: {trend} ({oi*100:+.2f}%). "
                    f"Scenario: {scene}. "
                    f"{'Rising OI + rising price = new longs adding.' if 'NEW_LONGS' in scene else ''}")

        if "liquidation" in q or "cascade" in q or "squeeze" in q:
            if r.get("liq_detected"):
                return (f"Liquidation cascade detected: {r.get('liq_type','?')} — "
                        f"this typically accelerates price in the liquidation direction.")
            return "No liquidation cascade currently detected."

        if "long" in q and "short" in q or "ratio" in q or "crowd" in q:
            ratio = r.get("ls_ratio", 1.0)
            crowd = r.get("ls_crowd", "NEUTRAL")
            contr = r.get("ls_contrarian", "NEUTRAL")
            return (f"Long/Short ratio: {ratio:.2f} ({crowd}). "
                    f"When {crowd.lower()}, contrarian bias is {contr}. "
                    f"Extreme sentiment often precedes reversals.")

        if "taker" in q or "aggressor" in q:
            agg = r.get("taker_aggressor", "BALANCED")
            return f"Taker side: {agg}. This indicates who is initiating trades — market aggression."

        return super().answer(question, market_context)

    # ── Helpers ────────────────────────────────────────────────────────────

    def _classify_oi(self, trend: str, delta: float, price: float) -> str:
        if trend == "RISING":
            return "NEW_LONGS_ADDING"   # best case for continuation
        if trend == "FALLING" and delta < -0.005:
            return "SHORTS_COVERING"    # could mean squeeze
        return "OI_STABLE"

    def _determine_signal(
        self,
        oi_trend, oi_delta, oi_scenario,
        funding_rate, funding_ext, funding_bias,
        ls_ratio, ls_contrarian,
        taker_agg, taker_buy,
        liq_detected, liq_type,
    ):
        bull_score = 0
        bear_score = 0

        # OI
        if oi_trend == "RISING" and oi_delta > 0.003:
            bull_score += 2   # new money entering — direction matters
        elif oi_trend == "FALLING":
            bear_score += 1   # de-risking

        # Funding — contrarian: extreme long funding = bearish pressure
        if funding_ext and "LONG" in funding_bias:
            bear_score += 2   # longs over-extended
        elif funding_ext and "SHORT" in funding_bias:
            bull_score += 2   # shorts over-extended
        elif funding_rate < -0.0002:
            bull_score += 1   # slightly negative = contrarian long

        # L/S ratio
        if ls_ratio > 1.5:    bear_score += 1   # longs crowded
        elif ls_ratio < 0.7:  bull_score += 1   # shorts crowded

        # Taker
        if taker_buy > 0.58:  bull_score += 1
        elif taker_buy < 0.42: bear_score += 1

        # Liquidations (acceleration factor)
        if liq_detected and "SHORT" in liq_type:
            bull_score += 2   # shorts being squeezed
        elif liq_detected and "LONG" in liq_type:
            bear_score += 2   # longs being cascaded

        if bull_score > bear_score and bull_score >= 3:
            conf    = min(100.0, bull_score / 8 * 100)
            signal  = "LONG"
            summary = self._summary("LONG", oi_trend, oi_delta, funding_rate, funding_ext, funding_bias, ls_ratio)
        elif bear_score > bull_score and bear_score >= 3:
            conf    = min(100.0, bear_score / 8 * 100)
            signal  = "SHORT"
            summary = self._summary("SHORT", oi_trend, oi_delta, funding_rate, funding_ext, funding_bias, ls_ratio)
        else:
            conf    = 0.0
            signal  = "NEUTRAL"
            summary = (f"Mixed futures signals. OI {oi_trend} | "
                       f"Funding {funding_rate*100:.4f}% | L/S {ls_ratio:.2f}.")

        return signal, conf, summary

    def _summary(self, direction, oi_trend, oi_delta, fr, fr_ext, fr_bias, ls) -> str:
        parts = [f"OI {oi_trend} {oi_delta*100:+.2f}%"]
        if fr_ext:
            parts.append(f"extreme funding {fr*100:.4f}% ({fr_bias})")
        else:
            parts.append(f"funding {fr*100:.4f}%")
        parts.append(f"L/S {ls:.2f}")
        return f"{' | '.join(parts)} → {direction}"

    def _oi_verdict(self, trend, delta, signal):
        if trend == "RISING" and signal == "LONG": return "SUPPORTS"
        if trend == "RISING" and signal == "SHORT": return "OPPOSES"
        return "NEUTRAL"

    def _funding_verdict(self, rate, extreme, signal):
        if extreme:
            # extreme funding opposes the crowded side
            if rate > 0 and signal == "SHORT": return "SUPPORTS"
            if rate > 0 and signal == "LONG":  return "OPPOSES"
            if rate < 0 and signal == "LONG":  return "SUPPORTS"
        return "NEUTRAL"

    def _ls_verdict(self, ratio, contrarian, signal):
        if contrarian == "LONG"  and signal == "LONG":  return "SUPPORTS"
        if contrarian == "SHORT" and signal == "SHORT": return "SUPPORTS"
        if contrarian == "LONG"  and signal == "SHORT": return "OPPOSES"
        if contrarian == "SHORT" and signal == "LONG":  return "OPPOSES"
        return "NEUTRAL"

    def _liq_verdict(self, detected, liq_type, signal):
        if not detected: return "NEUTRAL"
        if "SHORT" in liq_type and signal == "LONG":  return "SUPPORTS"
        if "LONG"  in liq_type and signal == "SHORT": return "SUPPORTS"
        return "OPPOSES"
