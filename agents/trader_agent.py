"""
Trader Agent

Tracks open positions, entry/exit logic, and execution status.
Drives the TRADER NPC in the Pixel Office.
"""

from __future__ import annotations
from events.event_bus import brain_pub
from .base_agent import BaseAgent, AgentReport


class TraderAgent(BaseAgent):
    AGENT_NAME = "TRADER"

    def analyse(self, market_context: dict) -> AgentReport:
        pos      = market_context.get("open_position", None)
        mark     = market_context.get("mark_price", 0.0)
        decision = market_context.get("_ceo_decision", {})

        if pos is None:
            signal    = "NEUTRAL"
            conf      = 0.0
            summary   = "No open position. Watching for entry signal."
            factors   = [self._factor("Position", "FLAT", "NEUTRAL", "Awaiting CEO decision")]
        else:
            direction = pos.get("direction", "LONG")
            entry     = pos.get("entry_price", mark)
            qty       = pos.get("quantity", 0.0)
            pnl       = pos.get("unrealised_pnl", (mark - entry) * qty if direction == "LONG" else (entry - mark) * qty)
            sl        = pos.get("stop_loss", 0.0)
            tp        = pos.get("take_profit", 0.0)

            signal  = direction
            conf    = 100.0
            summary = (f"Holding {direction} {qty:.4f} BTC @ {entry:.2f} | "
                       f"uPnL {pnl:+.2f} USDT | SL={sl:.0f} TP={tp:.0f}")

            sl_dist = abs(mark - sl) / mark * 100 if sl else 0
            tp_dist = abs(tp - mark) / mark * 100 if tp else 0

            if pnl > 0:
                brain_pub.info("POSITION_PROFITABLE",
                               f"Position {direction} up {pnl:+.2f} USDT",
                               {"pnl": pnl, "qty": qty})
            elif pnl < 0 and abs(pnl) > 10:
                brain_pub.warning("POSITION_LOSING",
                                  f"Position {direction} down {pnl:.2f} USDT",
                                  {"pnl": pnl, "sl": sl})

            factors = [
                self._factor("Position", f"{direction} {qty:.4f} BTC", "SUPPORTS", f"Entry: {entry:.2f}"),
                self._factor("uPnL", f"{pnl:+.2f} USDT", "SUPPORTS" if pnl > 0 else "OPPOSES", "Unrealised P&L"),
                self._factor("Stop Loss", f"{sl:.0f} ({sl_dist:.2f}% away)", "SUPPORTS", "Risk guard"),
                self._factor("Take Profit", f"{tp:.0f} ({tp_dist:.2f}% away)", "SUPPORTS", "Exit target"),
            ]

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = conf,
            summary    = summary,
            factors    = factors,
            raw        = {"open_position": pos, "mark_price": mark},
            event_name = None if pos is None else "POSITION_STATUS",
        )

    def answer(self, question: str, market_context: dict | None = None) -> str:
        last = self._last
        if last is None: return "No trader data yet."
        pos = last.raw.get("open_position"); q = question.lower()
        if not pos:
            return "No open position currently. Waiting for a valid entry signal."
        if "entry" in q or "price" in q:
            return f"Entry price: {pos.get('entry_price',0):.2f} USDT in {pos.get('direction','?')} direction."
        if "sl" in q or "stop" in q:
            return f"Stop Loss: {pos.get('stop_loss',0):.2f} USDT."
        if "tp" in q or "target" in q or "take profit" in q:
            return f"Take Profit: {pos.get('take_profit',0):.2f} USDT."
        if "pnl" in q or "profit" in q or "loss" in q:
            pnl = pos.get("unrealised_pnl", 0)
            return f"Unrealised PnL: {pnl:+.2f} USDT."
        return super().answer(question, market_context)
