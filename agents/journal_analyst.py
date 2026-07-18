"""
Journal Analyst Agent

Analyses trade history to produce performance insights.
Answers questions like "Last 14 similar setups → 63% win rate."
Drives the JOURNAL NPC in the Pixel Office.
"""

from __future__ import annotations
from typing import Optional
from .base_agent import BaseAgent, AgentReport


class JournalAnalyst(BaseAgent):
    AGENT_NAME = "JOURNAL_ANALYST"

    def __init__(self, journal=None) -> None:
        super().__init__()
        self._journal = journal

    def analyse(self, market_context: dict) -> AgentReport:
        j = self._journal
        perf = {}
        daily = {}
        if j is not None:
            try:
                perf  = j.get_performance_summary() or {}
                daily = j.get_daily_stats() or {}
            except Exception:
                pass

        total   = int(perf.get("total_trades", 0) or 0)
        wins    = int(perf.get("winning_trades", 0) or 0)
        losses  = int(perf.get("losing_trades", 0) or 0)
        wr      = float(perf.get("win_rate", 0.0) or 0.0)
        pf      = float(perf.get("profit_factor", 0.0) or 0.0)
        exp     = float(perf.get("expectancy", 0.0) or 0.0)
        max_dd  = float(perf.get("max_drawdown", 0.0) or 0.0)
        today_pnl = float(daily.get("day_pnl", 0.0) or 0.0)

        if total == 0:
            signal  = "NEUTRAL"
            conf    = 0.0
            summary = "No trade history yet. Journal is empty."
        elif wr > 55 and pf > 1.5:
            signal  = "LONG"   # system is performing well
            conf    = min(100.0, wr)
            summary = f"{total} trades | WR {wr:.1f}% | PF {pf:.2f} | Edge confirmed"
        elif wr < 40 or pf < 0.8:
            signal  = "NEUTRAL"   # caution
            conf    = 0.0
            summary = f"{total} trades | WR {wr:.1f}% | PF {pf:.2f} | Edge weak — review strategy"
        else:
            signal  = "NEUTRAL"
            conf    = 50.0
            summary = f"{total} trades | WR {wr:.1f}% | PF {pf:.2f} | Developing"

        factors = [
            self._factor("Win Rate",     f"{wr:.1f}%",          "SUPPORTS" if wr > 50 else "OPPOSES",  f"{wins}W / {losses}L"),
            self._factor("Profit Factor",f"{pf:.2f}",           "SUPPORTS" if pf > 1.2 else "OPPOSES", "PF > 1.5 = strong edge"),
            self._factor("Expectancy",   f"{exp:+.2f} USDT",    "SUPPORTS" if exp > 0 else "OPPOSES",  "Avg expected per trade"),
            self._factor("Max Drawdown", f"{max_dd:.2f}%",      "NEUTRAL",                             "Largest peak-to-trough"),
            self._factor("Today PnL",    f"{today_pnl:+.2f} U", "SUPPORTS" if today_pnl >= 0 else "OPPOSES", "Current session"),
        ]

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = conf,
            summary    = summary,
            factors    = factors,
            raw        = {"total": total, "win_rate": wr, "profit_factor": pf,
                          "expectancy": exp, "max_drawdown": max_dd,
                          "today_pnl": today_pnl, "wins": wins, "losses": losses},
        )

    def answer(self, question: str, market_context: Optional[dict] = None) -> str:
        last = self._last
        if last is None: return "No journal data yet."
        r = last.raw; q = question.lower()
        if "win rate" in q or "wr" in q:
            return f"Win rate: {r.get('win_rate',0):.1f}% over {r.get('total',0)} trades ({r.get('wins',0)}W / {r.get('losses',0)}L)."
        if "profit factor" in q or "pf" in q:
            pf = r.get("profit_factor", 0)
            return f"Profit factor: {pf:.2f}. {'>1.5 = excellent edge' if pf > 1.5 else '>1.0 = positive edge' if pf > 1.0 else 'Below 1.0 = losing system'}."
        if "expectancy" in q:
            return f"Expectancy: {r.get('expectancy',0):+.2f} USDT per trade. Positive = edge exists."
        if "drawdown" in q:
            return f"Max drawdown: {r.get('max_drawdown',0):.2f}%."
        if "today" in q or "session" in q:
            return f"Today's PnL: {r.get('today_pnl',0):+.2f} USDT."
        return super().answer(question, market_context)
