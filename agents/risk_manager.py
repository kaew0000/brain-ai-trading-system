"""
Risk Manager Agent

Translates RiskEngine outputs into AI agent reports.
Publishes events: TRADE_BLOCKED, DAILY_LIMIT_NEAR, CONSECUTIVE_LOSS, RISK_APPROVED.
"""

from __future__ import annotations
from config.settings import settings
from events.event_bus import risk_pub
from utils.logger import get_logger
from .base_agent import BaseAgent, AgentReport

logger = get_logger(__name__)


class RiskManagerAgent(BaseAgent):
    AGENT_NAME = "RISK_MANAGER"

    def __init__(self, risk_engine=None, journal=None) -> None:
        super().__init__()
        self._risk_engine = risk_engine
        self._journal     = journal

    def analyse(self, market_context: dict) -> AgentReport:
        balance = market_context.get("balance", 10_000.0)

        # v16 consolidation: numbers now come from the injected RiskEngine —
        # the same engine main.py wires as `risk_engine` and checks directly
        # before every order (main.py: rsk.can_trade(balance)). This agent
        # used to recompute daily-loss / consecutive-loss / risk-pct itself
        # from `journal.get_daily_stats()["day_pnl"]` and
        # `[...]["consecutive_losses"]` — keys TradeJournalV2.get_daily_stats()
        # never actually returns (it returns "total_pnl", and consecutive-loss
        # count lives in the separate get_consecutive_losses() method). That
        # meant today_pnl/consec_loss were silently always 0 here, so this
        # agent's HALT/ELEVATED/CAUTION classification, its DAILY_LIMIT_HIT /
        # DAILY_LIMIT_NEAR / CONSECUTIVE_LOSS events, and its own can_trade
        # (read by CEOAgent.decide() as risk_blocked, ceo_agent.py L151-153)
        # never reflected real risk state. The real trading gate was never
        # affected by this — RiskEngine.can_trade() in main.py is independent
        # of the agent layer — but this agent's dashboard narrative, its
        # answer() Q&A, and the CEO's own (redundant) veto consistency were
        # silently wrong. Delegating to RiskEngine fixes the data bug and
        # makes it structurally impossible for the two to disagree again.
        if self._risk_engine is not None:
            report = self._risk_engine.report(balance)
        else:
            # Defensive fallback for construction without a wired RiskEngine
            # (e.g. an ad-hoc script). main.py always wires a real one via
            # build_agent_layer(risk_engine=...) — this path is not expected
            # in production and is logged so it's visible if it ever is hit.
            logger.warning(
                "RiskManagerAgent has no risk_engine wired in — reporting a "
                "default 'clear' state instead of a real risk verdict"
            )
            report = {
                "can_trade": True, "block_reason": "", "disabled_today": False,
                "consecutive_losses": 0, "today_pnl": 0.0,
                "max_daily_loss_u": round(balance * settings.MAX_DAILY_LOSS, 2),
                "dynamic_risk_pct": settings.RISK_PER_TRADE_MAX,
            }

        can_trade      = report["can_trade"]
        today_pnl      = report["today_pnl"]
        consec_loss    = report["consecutive_losses"]
        risk_pct       = report["dynamic_risk_pct"]
        max_daily_loss = report["max_daily_loss_u"]
        block_reason   = report.get("block_reason", "")
        blocks: list   = [block_reason] if block_reason else []

        # Priority-based classification (HALT always wins) rather than the
        # previous two-independent-if/elif-blocks shape, where a consec-loss
        # check running after the daily-loss check could silently downgrade
        # risk_level from HALT to CAUTION when both conditions were true.
        daily_halt  = today_pnl < -max_daily_loss
        daily_warn  = today_pnl < -max_daily_loss * 0.7
        consec_halt = consec_loss >= settings.MAX_CONSECUTIVE_LOSSES
        consec_warn = consec_loss >= settings.MAX_CONSECUTIVE_LOSSES - 1

        if daily_halt:
            risk_pub.critical("DAILY_LIMIT_HIT",
                              f"Daily loss {today_pnl:.2f} USDT — trading halted",
                              {"pnl": today_pnl, "limit": -max_daily_loss})
        if consec_halt:
            risk_pub.warning("CONSECUTIVE_LOSS",
                             f"{consec_loss} consecutive losses — trading paused",
                             {"count": consec_loss})
        if not daily_halt and daily_warn:
            risk_pub.warning("DAILY_LIMIT_NEAR",
                             f"Daily loss {today_pnl:.2f} USDT approaching limit",
                             {"pnl": today_pnl})

        if daily_halt or consec_halt:
            risk_level = "HALT"
        elif daily_warn:
            risk_level = "ELEVATED"
        elif consec_warn:
            risk_level = "CAUTION"
        else:
            risk_level = "NORMAL"

        if can_trade:
            risk_pub.info("RISK_APPROVED",
                          f"Circuit breaker clear | risk per trade would be {risk_pct*100:.1f}% | PnL {today_pnl:+.2f}",
                          {"can_trade": True, "risk_pct": risk_pct})

        drawdown_pct = abs(today_pnl / balance * 100) if balance else 0.0

        # Bug fix: RiskManager has no opinion on market direction — it only
        # reports whether the circuit breaker is tripped. Previously this
        # was reported as signal="LONG" whenever can_trade was True, which
        # is *almost always*. CEOAgent.decide() weighs any "risk" report
        # with signal=="LONG" into long_score at 15% weight, so every cycle
        # the circuit breaker wasn't tripped silently added +15 points to
        # long_score regardless of actual market direction — inflating
        # CEO's long bias on every single tick, including while a position
        # was already open and being re-scored for the dashboard refresh.
        # The veto path (risk_blocked in ceo_agent.py) already reads
        # raw["can_trade"] directly and is unaffected by this — only the
        # directional vote was wrong. Always report NEUTRAL here; "approved/
        # blocked" status still lives in raw["can_trade"] and confidence.
        signal     = "NEUTRAL"
        confidence = 100.0 if can_trade else 0.0

        factors = [
            self._factor("Daily PnL",
                         f"{today_pnl:+.2f} USDT ({drawdown_pct:.2f}%)",
                         "SUPPORTS" if today_pnl >= 0 else "OPPOSES" if abs(today_pnl) > max_daily_loss * 0.5 else "NEUTRAL",
                         f"Limit: {max_daily_loss:.2f} USDT"),
            self._factor("Consecutive Losses",
                         str(consec_loss),
                         "OPPOSES" if consec_loss >= 2 else "SUPPORTS" if consec_loss == 0 else "NEUTRAL",
                         f"Max allowed: {settings.MAX_CONSECUTIVE_LOSSES}"),
            self._factor("Risk Per Trade",
                         f"{risk_pct*100:.1f}%",
                         "SUPPORTS" if risk_pct >= settings.RISK_PER_TRADE_MIN else "NEUTRAL",
                         f"Range: {settings.RISK_PER_TRADE_MIN*100:.1f}%-{settings.RISK_PER_TRADE_MAX*100:.1f}%"),
            self._factor("Circuit Breaker",
                         "ACTIVE" if not can_trade else "INACTIVE",
                         "OPPOSES" if not can_trade else "SUPPORTS",
                         " | ".join(blocks) if blocks else "All checks passed"),
        ]

        summary = (f"Risk {risk_level} | PnL {today_pnl:+.2f} USDT | "
                   f"Consec losses: {consec_loss} | "
                   f"{'CIRCUIT BREAKER CLEAR' if can_trade else 'CIRCUIT BREAKER TRIPPED: ' + blocks[0] if blocks else 'CIRCUIT BREAKER TRIPPED'}")

        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = signal,
            confidence = confidence,
            summary    = summary,
            factors    = factors,
            raw        = {
                "can_trade":    can_trade,
                "today_pnl":   today_pnl,
                "drawdown_pct": drawdown_pct,
                "consec_loss": consec_loss,
                "risk_pct":    risk_pct,
                "risk_level":  risk_level,
                "blocks":      blocks,
                "balance":     balance,
            },
        )

    def answer(self, question: str, market_context: dict | None = None) -> str:
        last = self._last
        if last is None: return "No risk assessment available yet."
        r = last.raw; q = question.lower()

        if "drawdown" in q or "loss" in q:
            return (f"Today's PnL: {r.get('today_pnl',0):+.2f} USDT "
                    f"({r.get('drawdown_pct',0):.2f}% drawdown). "
                    f"Max daily limit: {r.get('balance',10000)*settings.MAX_DAILY_LOSS:.2f} USDT.")

        if "consecutive" in q or "streak" in q:
            cl = r.get("consec_loss", 0)
            return (f"{cl} consecutive losing trades. "
                    f"Max allowed: {settings.MAX_CONSECUTIVE_LOSSES}. "
                    f"{'Trading halted.' if cl >= settings.MAX_CONSECUTIVE_LOSSES else 'Still within limits.'}")

        if "risk" in q and ("size" in q or "per trade" in q or "pct" in q):
            rp = r.get("risk_pct", 0)
            return (f"Current risk per trade: {rp*100:.1f}%. "
                    f"This scales down after losses to protect capital.")

        if "can trade" in q or "approved" in q or "blocked" in q:
            if r.get("can_trade"):
                return f"Trading APPROVED. Risk level: {r.get('risk_level','?')}."
            return f"Trading BLOCKED. Reason: {r.get('blocks',['unknown'])[0] if r.get('blocks') else 'circuit breaker active'}."

        return super().answer(question, market_context)
