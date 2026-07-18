"""
SMC Analyst Agent

Analyses Smart Money Concepts signals across all timeframes:
  H4, H1, M15 — BOS, CHoCH, FVG, Order Block, Liquidity

Publishes specific events to EventBus:
  BOS_DETECTED, CHOCH_DETECTED, FVG_DETECTED, OB_DETECTED,
  MTF_ALIGNED, MTF_CONFLICTING, STRUCTURE_BULLISH, STRUCTURE_BEARISH

NPC speech driven by actual signal state — no demo text.
"""

from __future__ import annotations

from events.event_bus import smc_pub
from .base_agent import BaseAgent, AgentReport


class SMCAnalyst(BaseAgent):
    """AI employee responsible for Smart Money Concepts analysis."""

    AGENT_NAME = "SMC_ANALYST"

    def analyse(self, market_context: dict) -> AgentReport:
        m15 = market_context.get("smc_m15", {})
        h1  = market_context.get("smc_h1",  {})
        h4  = market_context.get("smc_h4",  {})

        # ── Extract signals ────────────────────────────────────────────────
        bos         = bool(m15.get("bos",   False))
        bos_dir     = m15.get("bos_dir",    "")
        choch       = bool(m15.get("choch", False))
        choch_dir   = m15.get("choch_dir",  "")
        fvg         = bool(m15.get("fvg",   False))
        fvg_dir     = m15.get("fvg_dir",    "")
        ob          = bool(m15.get("ob",    False))
        ob_dir      = m15.get("ob_dir",     "")
        mtf_aligned = bool(market_context.get("mtf_aligned", False))
        mtf_dir     = market_context.get("mtf_direction", "")
        trend_bias  = m15.get("trend_bias", "NEUTRAL")

        liq_high    = m15.get("liquidity_high", 0.0)
        liq_low     = m15.get("liquidity_low",  0.0)
        prev_high   = m15.get("prev_high", 0.0)
        prev_low    = m15.get("prev_low",  0.0)

        # H4/H1 agreement
        h4_bias = h4.get("trend_bias", "")
        h1_bias = h1.get("trend_bias", "")
        h4_bos  = bool(h4.get("bos", False))
        h1_bos  = bool(h1.get("bos", False))

        # ── Signal detection + EventBus publish ───────────────────────────
        if bos:
            smc_pub.info("BOS_DETECTED",
                         f"{'Bullish' if 'ullish' in bos_dir or bos_dir=='LONG' else 'Bearish'} BOS on M15",
                         {"direction": bos_dir, "timeframe": "M15"})
        if choch:
            smc_pub.info("CHOCH_DETECTED",
                         f"CHoCH {'bullish' if 'ullish' in choch_dir else 'bearish'} shift on M15",
                         {"direction": choch_dir})
        if fvg:
            smc_pub.info("FVG_DETECTED",
                         f"Fair Value Gap {fvg_dir} on M15 — potential entry zone",
                         {"direction": fvg_dir})
        if ob:
            smc_pub.info("OB_DETECTED",
                         f"Order Block {ob_dir} on M15",
                         {"direction": ob_dir, "top": m15.get("ob_top", 0), "bottom": m15.get("ob_bottom", 0)})

        if mtf_aligned:
            smc_pub.info("MTF_ALIGNED",
                         f"Multi-timeframe aligned {mtf_dir}",
                         {"direction": mtf_dir})
        elif mtf_dir:
            smc_pub.warning("MTF_CONFLICTING",
                            f"MTF not fully aligned — partial {mtf_dir}",
                            {"direction": mtf_dir})

        # ── Score ──────────────────────────────────────────────────────────
        bullish_pts = sum([
            bos and ("ullish" in bos_dir or bos_dir in ("LONG","Bullish")),
            choch and ("ullish" in choch_dir or choch_dir in ("LONG","Bullish")),
            fvg and ("ullish" in fvg_dir or fvg_dir in ("LONG","Bullish")),
            ob and ("ullish" in ob_dir or ob_dir in ("LONG","Bullish")),
            mtf_aligned and mtf_dir == "LONG",
            "LONG" in trend_bias or "ullish" in trend_bias,
            h4_bos,
        ])
        bearish_pts = sum([
            bos and ("earish" in bos_dir or bos_dir in ("SHORT","Bearish")),
            choch and ("earish" in choch_dir or choch_dir in ("SHORT","Bearish")),
            fvg and ("earish" in fvg_dir or fvg_dir in ("SHORT","Bearish")),
            ob and ("earish" in ob_dir or ob_dir in ("SHORT","Bearish")),
            mtf_aligned and mtf_dir == "SHORT",
            "SHORT" in trend_bias or "earish" in trend_bias,
        ])

        if bullish_pts > bearish_pts and bullish_pts >= 2:
            signal     = "LONG"
            confidence = min(100.0, bullish_pts / 7 * 100)
        elif bearish_pts > bullish_pts and bearish_pts >= 2:
            signal     = "SHORT"
            confidence = min(100.0, bearish_pts / 7 * 100)
        else:
            signal     = "NEUTRAL"
            confidence = 0.0

        # ── Build factors list ─────────────────────────────────────────────
        def _dir_verdict(detected: bool, direction: str, wanted: str) -> str:
            if not detected: return "NEUTRAL"
            return "SUPPORTS" if (wanted in direction or direction == wanted) else "OPPOSES"

        factors = [
            self._factor("BOS",
                         f"{bos_dir}" if bos else "None",
                         _dir_verdict(bos, bos_dir, signal),
                         f"Break of Structure on M15: {'detected' if bos else 'not detected'}"),
            self._factor("CHoCH",
                         f"{choch_dir}" if choch else "None",
                         _dir_verdict(choch, choch_dir, signal),
                         f"Change of Character: {'detected' if choch else 'not detected'}"),
            self._factor("FVG",
                         f"{fvg_dir}" if fvg else "None",
                         _dir_verdict(fvg, fvg_dir, signal),
                         f"Fair Value Gap: {'entry zone present' if fvg else 'no FVG'}"),
            self._factor("Order Block",
                         f"{ob_dir}" if ob else "None",
                         _dir_verdict(ob, ob_dir, signal),
                         f"OB: {'present' if ob else 'absent'}"),
            self._factor("MTF Alignment",
                         f"{mtf_dir} ({'aligned' if mtf_aligned else 'partial'})",
                         "SUPPORTS" if mtf_aligned and mtf_dir == signal else "NEUTRAL",
                         f"H4/H1/M15 bias: {h4_bias}/{h1_bias}/{trend_bias}"),
            self._factor("Liquidity",
                         f"H={liq_high:.0f} L={liq_low:.0f}" if liq_high else "—",
                         "NEUTRAL",
                         f"Prev high={prev_high:.0f} Prev low={prev_low:.0f}"),
        ]

        summary = self._build_summary(signal, bos, bos_dir, choch, fvg, ob, mtf_aligned, mtf_dir)

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = confidence,
            summary    = summary,
            factors    = factors,
            raw        = {
                "bos": bos, "bos_dir": bos_dir,
                "choch": choch, "choch_dir": choch_dir,
                "fvg": fvg, "fvg_dir": fvg_dir,
                "ob": ob, "ob_dir": ob_dir,
                "mtf_aligned": mtf_aligned, "mtf_direction": mtf_dir,
                "trend_bias": trend_bias,
                "liquidity_high": liq_high, "liquidity_low": liq_low,
                "h4_bias": h4_bias, "h1_bias": h1_bias,
            },
        )

    def answer(self, question: str, market_context: Optional[dict] = None) -> str:  # noqa: F821
        last = self._last
        if last is None:
            return "No SMC analysis available yet."

        r   = last.raw
        q   = question.lower()

        if "fvg" in q or "fair value" in q:
            if r.get("fvg"):
                return (f"FVG detected on M15 — direction: {r.get('fvg_dir','?')}. "
                        f"This is a potential entry zone where price may return to fill the gap.")
            return "No Fair Value Gap currently detected on M15."

        if "ob" in q or "order block" in q:
            if r.get("ob"):
                return (f"Order Block present — direction: {r.get('ob_dir','?')}. "
                        f"This institutional supply/demand zone supports {last.signal} entries.")
            return "No active Order Block detected."

        if "liquidity" in q or "sweep" in q:
            hi = r.get("liquidity_high", 0)
            lo = r.get("liquidity_low",  0)
            if hi or lo:
                return (f"Liquidity pools: above at {hi:.0f} USDT, below at {lo:.0f} USDT. "
                        f"Smart money typically sweeps liquidity before reversals.")
            return "No significant liquidity pools mapped at this time."

        if "bos" in q or "break of structure" in q:
            if r.get("bos"):
                return f"BOS detected on M15 — {r.get('bos_dir','?')} direction confirms structure shift."
            return "No Break of Structure detected on M15."

        if "choch" in q or "change of character" in q:
            if r.get("choch"):
                return f"CHoCH detected — {r.get('choch_dir','?')}. Trend may be reversing."
            return "No Change of Character detected."

        if "mtf" in q or "multi" in q or "timeframe" in q:
            aligned = r.get("mtf_aligned")
            mtf_dir = r.get("mtf_direction","")
            if aligned:
                return f"All three timeframes (H4/H1/M15) are aligned {mtf_dir}. Strong confluence."
            elif mtf_dir:
                return f"Partial MTF alignment {mtf_dir}. H4: {r.get('h4_bias','?')}, M15: {r.get('trend_bias','?')}."
            return "No MTF alignment. Timeframes are conflicting — avoid trading."

        if "why" in q and ("long" in q or "short" in q or "reject" in q):
            return last.summary

        return super().answer(question, market_context)

    def _build_summary(self, signal, bos, bos_dir, choch, fvg, ob, mtf_aligned, mtf_dir) -> str:
        parts = []
        if bos:   parts.append(f"BOS {bos_dir}")
        if choch: parts.append(f"CHoCH {choch_dir}" if (choch_dir := "") is None else f"CHoCH detected")
        if fvg:   parts.append("FVG entry zone")
        if ob:    parts.append("Order Block present")
        if mtf_aligned: parts.append(f"MTF aligned {mtf_dir}")

        if not parts:
            return "No clear SMC structure — waiting for signal."
        base = " + ".join(parts)
        return f"{base} → {signal}" if signal != "NEUTRAL" else f"{base} — no trade signal."


from typing import Optional  # noqa: E402 (keep at bottom to avoid circular)
