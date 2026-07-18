"""
CEO Agent

Consumes ALL agent reports and produces the final trading decision.

The CEO is the orchestrator. It:
  1. Collects AgentReport from each AI employee
  2. Weighs their signals and confidence scores
  3. Cross-validates with the existing ConfidenceEngine output
  4. Produces a final CEODecision with full explainability
  5. Answers any chat question by delegating to the appropriate agent

CEODecision schema
------------------
{
  "action":       "LONG" | "SHORT" | "WAIT",
  "direction":    str,
  "confidence":   float 0-100,
  "score_breakdown": {
    "smc":     float,
    "futures": float,
    "regime":  float,
    "risk":    float,
    "journal": float,
  },
  "reasons":    [str, ...],
  "agent_reports": { agent_name: AgentReport.to_dict() },
  "timestamp":  str,
}

Does NOT replace ConfidenceEngine — augments it with agent reasoning layer.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from typing import Optional

from events.event_bus import conf_pub
from telemetry.agent_telemetry import get_telemetry_registry
from reasoning.reasoning_stream import get_reasoning_stream
from utils.logger import get_logger
from .base_agent import BaseAgent, AgentReport

logger = get_logger("agents.ceo_agent")


@dataclass
class CEODecision:
    action:          str  = "WAIT"
    direction:       str  = ""
    confidence:      float = 0.0
    score_breakdown: dict  = field(default_factory=dict)
    reasons:         list  = field(default_factory=list)
    agent_reports:   dict  = field(default_factory=dict)
    timestamp:       str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "action":          self.action,
            "direction":       self.direction,
            "confidence":      self.confidence,
            "score_breakdown": self.score_breakdown,
            "reasons":         self.reasons,
            "agent_reports":   self.agent_reports,
            "timestamp":       self.timestamp,
        }

    def npc_speech(self) -> str:
        """One-line summary for CEO NPC speech bubble."""
        if self.action == "WAIT":
            return f"Waiting. Confidence {self.confidence:.0f}%."
        return f"{self.action} signal. Confidence {self.confidence:.0f}%. {self.reasons[0] if self.reasons else ''}"


class CEOAgent(BaseAgent):
    """
    AI CEO — orchestrates all agent reports into a final decision.

    Parameters
    ----------
    agents : dict of agent_name -> BaseAgent instance
    """

    AGENT_NAME = "CEO_AGENT"

    # Weights for CEO's own scoring (separate from ConfidenceEngine)
    WEIGHTS = {
        "smc":     0.30,
        "futures": 0.25,
        "regime":  0.20,
        "risk":    0.15,
        "journal": 0.10,
    }

    def __init__(self, agents: Optional[dict] = None) -> None:
        super().__init__()
        self._agents: dict = agents or {}
        self._last_ceo:  Optional[CEODecision] = None

    def register_agent(self, name: str, agent: BaseAgent) -> None:
        self._agents[name] = agent

    def decide(
        self,
        market_context: dict,
        confidence_result=None,    # ConfidenceResult from existing engine (optional)
    ) -> CEODecision:
        """
        Run all agents, combine their signals, produce a CEODecision.

        If confidence_result is provided, it is used as the primary signal
        and CEO augments it with reasoning. Otherwise CEO decides independently.

        Telemetry (v14 Phase 2): each sub-agent already records its own
        telemetry via BaseAgent.run(). This method additionally records
        telemetry for the CEO_AGENT itself, timing the full orchestration
        (sub-agent loop + aggregation + decision construction).
        """
        _telemetry_start = time.perf_counter()

        # ── Run all agents ────────────────────────────────────────────────
        reports: dict[str, AgentReport] = {}
        for name, agent in self._agents.items():
            try:
                reports[name] = agent.run(market_context)
            except Exception as exc:
                logger.warning(f"Agent {name} failed: {exc}")

        # ── Aggregate signals ─────────────────────────────────────────────
        long_score  = 0.0
        short_score = 0.0
        reasons     = []

        for key, weight in self.WEIGHTS.items():
            rep = reports.get(key)
            if rep is None:
                continue
            w_conf = rep.confidence / 100 * weight * 100  # weighted pts

            if rep.signal == "LONG":
                long_score  += w_conf
                reasons.append(f"{rep.agent}: {rep.summary[:60]}")
            elif rep.signal == "SHORT":
                short_score += w_conf
                reasons.append(f"{rep.agent}: {rep.summary[:60]}")

        # Risk manager veto
        risk_rep = reports.get("risk")
        risk_blocked = (risk_rep is not None and
                        risk_rep.raw.get("can_trade") is False)

        # ── Determine action ──────────────────────────────────────────────
        if confidence_result is not None:
            # Prefer existing ConfidenceEngine's action (already tested and trusted)
            action     = getattr(confidence_result, "action", "WAIT")
            direction  = getattr(confidence_result, "direction", "")
            conf       = float(getattr(confidence_result, "confidence", 0.0))
            if risk_blocked and action in ("LONG", "SHORT"):
                action = "WAIT"
                conf   = 0.0
                reasons.insert(0, "RISK_MANAGER: trade blocked by circuit breaker")
        else:
            # CEO decides independently
            if risk_blocked:
                action, direction, conf = "WAIT", "", 0.0
                reasons.insert(0, "RISK_MANAGER: circuit breaker active")
            elif long_score > short_score and long_score >= 40:
                action, direction, conf = "LONG", "LONG", min(100.0, long_score)
            elif short_score > long_score and short_score >= 40:
                action, direction, conf = "SHORT", "SHORT", min(100.0, short_score)
            else:
                action, direction, conf = "WAIT", "", max(long_score, short_score)

        # ── Publish CEO decision event ─────────────────────────────────────
        payload = {
            "action":     action,
            "confidence": conf,
            "long_score": long_score,
            "short_score":short_score,
        }
        if action in ("LONG", "SHORT"):
            conf_pub.info("CEO_DECISION",
                          f"CEO says {action} @ {conf:.0f}% confidence",
                          payload)
        else:
            conf_pub.debug("CEO_WAIT",
                           f"CEO waiting — not enough signal ({conf:.0f}%)",
                           payload)

        dec = CEODecision(
            action          = action,
            direction       = direction,
            confidence      = round(conf, 2),
            score_breakdown = {
                "long_weighted":  round(long_score, 2),
                "short_weighted": round(short_score, 2),
                "smc":     round(reports.get("smc",    AgentReport("")).confidence * self.WEIGHTS.get("smc", 0), 2),
                "futures": round(reports.get("futures",AgentReport("")).confidence * self.WEIGHTS.get("futures", 0), 2),
                "regime":  round(reports.get("regime", AgentReport("")).confidence * self.WEIGHTS.get("regime", 0), 2),
                "risk":    round(reports.get("risk",   AgentReport("")).confidence * self.WEIGHTS.get("risk", 0), 2),
            },
            reasons       = reasons[:5],
            agent_reports = {k: v.to_dict() for k, v in reports.items()},
        )

        self._last_ceo = dec

        # ── Record CEO telemetry ────────────────────────────────────────────
        _latency_ms = round((time.perf_counter() - _telemetry_start) * 1000, 2)
        get_telemetry_registry().record(
            agent=self.AGENT_NAME,
            status="OK",
            confidence=dec.confidence,
            last_signal=dec.action if dec.action != "WAIT" else "NEUTRAL",
            latency_ms=_latency_ms,
            decision=dec.npc_speech(),
        )

        # ── Record CEO reasoning (v14 Phase 2.5) ────────────────────────────
        # "reasoning" = concatenated per-agent reasons already collected above;
        # falls back to a neutral statement when no agent contributed a signal.
        get_reasoning_stream().record(
            agent=self.AGENT_NAME,
            thought=dec.npc_speech(),
            reasoning="; ".join(reasons) if reasons else "No dominant signal from any sub-agent.",
            decision=dec.action,
            confidence=dec.confidence,
        )

        return dec

    def analyse(self, market_context: dict) -> AgentReport:
        """BaseAgent interface — wraps decide() without ConfidenceResult."""
        dec = self.decide(market_context)
        return AgentReport(
            agent      = self.AGENT_NAME,
            signal     = dec.action if dec.action != "WAIT" else "NEUTRAL",
            confidence = dec.confidence,
            summary    = dec.npc_speech(),
            raw        = dec.to_dict(),
        )

    def answer(self, question: str, market_context: Optional[dict] = None) -> str:
        """
        CEO answers by delegating to the appropriate agent.
        """
        q = question.lower()

        # Route to specific agent
        routing = {
            ("bos","choch","fvg","order block","structure","liquidity","smc"):          "smc",
            ("funding","oi","open interest","liquidation","long short","futures"):       "futures",
            ("regime","trend","adx","rsi","ema"):                                        "regime",
            ("risk","drawdown","daily loss","consecutive","circuit breaker","position size"): "risk",
            ("win rate","profit factor","expectancy","journal","history","performance"): "journal",
            ("entry","stop","take profit","position","pnl","unrealised"):               "trader",
        }

        for keywords, agent_key in routing.items():
            if any(kw in q for kw in keywords):
                agent = self._agents.get(agent_key)
                if agent and agent.last_report:
                    return agent.answer(question, market_context)

        # Generic CEO answer
        if self._last_ceo:
            d = self._last_ceo
            return (f"CEO decision: {d.action} @ {d.confidence:.0f}% confidence. "
                    f"Top reason: {d.reasons[0] if d.reasons else 'no strong signal'}.")
        return "CEO: No decision available yet. Waiting for first analysis cycle."

    @property
    def last_decision(self) -> Optional[CEODecision]:
        return self._last_ceo
