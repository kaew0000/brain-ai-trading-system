"""
Base Agent — AI Employee Framework

Every AI agent inherits from BaseAgent.

Responsibilities
----------------
- Subscribe to EventBus for events relevant to its domain
- Analyse market_context to produce a structured AgentReport
- Publish its own events back to EventBus for other agents / dashboard
- Answer questions from the CEO Agent or the user's chat interface

Design
------
- Pure Python (no async) — called synchronously from the trading cycle
- Stateless between calls EXCEPT for _memory (last N reports)
- Never fetches data itself — receives market_context dict

AgentReport schema
------------------
{
  "agent":      str,
  "timestamp":  str,
  "signal":     "LONG" | "SHORT" | "NEUTRAL" | "WAIT",
  "confidence": float 0-100,
  "summary":    str,
  "factors":    [{"name":str, "value":str, "verdict":str, "detail":str}],
  "raw":        dict   # engine-specific raw values
}
"""

from __future__ import annotations

import time
from collections import deque
from datetime import datetime, timezone
from typing import Optional

from events.event_bus import AgentPublisher
from telemetry.agent_telemetry import get_telemetry_registry
from reasoning.reasoning_stream import get_reasoning_stream
from utils.logger import get_logger


class AgentReport:
    """Structured output from any AI agent."""

    __slots__ = ("agent", "timestamp", "signal", "confidence",
                 "summary", "factors", "raw", "event_name")

    def __init__(
        self,
        agent:      str,
        signal:     str  = "NEUTRAL",
        confidence: float = 0.0,
        summary:    str  = "",
        factors:    Optional[list] = None,
        raw:        Optional[dict] = None,
        event_name: Optional[str] = None,
    ) -> None:
        self.agent      = agent
        self.timestamp  = datetime.now(timezone.utc).isoformat()
        self.signal     = signal
        self.confidence = round(float(confidence), 2)
        self.summary    = summary
        self.factors    = factors or []
        self.raw        = raw or {}
        # Optional override for the EventBus event name BaseAgent._publish()
        # uses. Defaults to None, which preserves the original
        # "{signal}_SIGNAL"/"ANALYSIS" auto-naming for every existing agent.
        # Lets an agent whose `signal` mirrors a status (e.g. "currently
        # holding LONG") rather than a fresh directional call avoid being
        # logged as a brand-new "LONG_SIGNAL"/"SHORT_SIGNAL" event.
        self.event_name = event_name

    def to_dict(self) -> dict:
        return {
            "agent":      self.agent,
            "timestamp":  self.timestamp,
            "signal":     self.signal,
            "confidence": self.confidence,
            "summary":    self.summary,
            "factors":    self.factors,
            "raw":        self.raw,
            "event_name": self.event_name,
        }

    def answer(self, question: str) -> str:
        """Default Q&A — overridden by each agent."""
        return f"[{self.agent}] No answer available. Last signal: {self.signal} — {self.summary}"


class BaseAgent:
    """
    Abstract AI employee base class.

    Subclasses must implement:
        analyse(market_context: dict) -> AgentReport
        answer(question: str, market_context: dict) -> str
    """

    AGENT_NAME: str = "BASE_AGENT"
    MEMORY_SIZE: int = 50

    def __init__(self) -> None:
        self._pub    = AgentPublisher(self.AGENT_NAME)
        self._memory: deque[AgentReport] = deque(maxlen=self.MEMORY_SIZE)
        self._last:   Optional[AgentReport] = None
        self._logger = get_logger(f"agents.{self.AGENT_NAME.lower()}")

    # ── Public interface ───────────────────────────────────────────────────

    def run(self, market_context: dict) -> AgentReport:
        """
        Entry point called every trading cycle.
        Wraps analyse() with memory storage, event publishing, telemetry,
        and reasoning-stream recording.

        Telemetry (v14 Phase 2): every call records latency, status,
        confidence, last_signal, and decision summary into the global
        TelemetryRegistry — consumed by GET /api/agents/telemetry and
        WS /ws/agents. Exceptions are recorded as status="ERROR" and then
        RE-RAISED unchanged, preserving the exact error-handling contract
        that existing callers (e.g. CEOAgent.decide()) already rely on.

        Reasoning Stream (v14 Phase 2.5): on success, also records a
        {agent, thought, reasoning, decision, confidence, timestamp} entry
        into the global ReasoningStream — consumed by the future Agent
        Debate Room dashboard page. Not recorded on error (no reasoning
        to show when analyse() raised).
        """
        registry = get_telemetry_registry()
        start = time.perf_counter()

        try:
            report = self.analyse(market_context)
        except Exception as exc:
            latency_ms = round((time.perf_counter() - start) * 1000, 2)
            registry.record(
                agent=self.AGENT_NAME,
                status="ERROR",
                confidence=0.0,
                last_signal=self._last.signal if self._last else "",
                latency_ms=latency_ms,
                decision=f"Exception: {exc}",
            )
            raise

        latency_ms = round((time.perf_counter() - start) * 1000, 2)

        self._memory.append(report)
        self._last = report
        self._publish(report)

        registry.record(
            agent=self.AGENT_NAME,
            status="OK",
            confidence=report.confidence,
            last_signal=report.signal,
            latency_ms=latency_ms,
            decision=report.summary,
        )

        get_reasoning_stream().record(
            agent=self.AGENT_NAME,
            thought=self._thought_text(report),
            reasoning=self._reasoning_text(report),
            decision=report.signal,
            confidence=report.confidence,
        )

        return report

    def _thought_text(self, report: AgentReport) -> str:
        """Short one-line internal monologue. Override for custom phrasing."""
        return report.summary or f"{self.AGENT_NAME} analysed and returned {report.signal}."

    def _reasoning_text(self, report: AgentReport) -> str:
        """
        Fuller narrative built from the report's structured factors.
        Override for custom phrasing — default joins each factor as
        "{name}: {value} ({verdict}) — {detail}".
        """
        if not report.factors:
            return report.summary or "No supporting factors recorded."
        parts = []
        for f in report.factors:
            name    = f.get("name", "")
            value   = f.get("value", "")
            verdict = f.get("verdict", "")
            detail  = f.get("detail", "")
            piece = f"{name}: {value} ({verdict})"
            if detail:
                piece += f" — {detail}"
            parts.append(piece)
        return "; ".join(parts)

    def analyse(self, market_context: dict) -> AgentReport:
        """Override in subclass."""
        raise NotImplementedError(f"{self.AGENT_NAME}.analyse() not implemented")

    def answer(self, question: str, market_context: Optional[dict] = None) -> str:
        """
        Answer a user question about the current market state.
        Uses last known report + market_context if provided.
        Override in subclass for domain-specific answers.
        """
        ctx = market_context or {}
        last = self._last
        if last is None:
            return f"[{self.AGENT_NAME}] No analysis run yet."

        q = question.lower().strip()

        # Generic fallbacks — subclasses override specific questions
        if any(w in q for w in ["why long", "long signal", "buy"]):
            if last.signal == "LONG":
                return f"{last.summary} | Confidence: {last.confidence:.0f}%"
            return f"No LONG signal. Current: {last.signal} — {last.summary}"

        if any(w in q for w in ["why short", "short signal", "sell"]):
            if last.signal == "SHORT":
                return f"{last.summary} | Confidence: {last.confidence:.0f}%"
            return f"No SHORT signal. Current: {last.signal} — {last.summary}"

        if any(w in q for w in ["status", "current", "now", "what"]):
            return f"{last.signal} | {last.confidence:.0f}% | {last.summary}"

        return f"[{self.AGENT_NAME}] Signal: {last.signal} | {last.summary}"

    @property
    def last_report(self) -> Optional[AgentReport]:
        return self._last

    def get_memory(self, n: int = 10) -> list[dict]:
        return [r.to_dict() for r in list(self._memory)[-n:]]

    # ── Internal ───────────────────────────────────────────────────────────

    def _publish(self, report: AgentReport) -> None:
        """Publish primary signal event to EventBus."""
        payload = {
            "signal":     report.signal,
            "confidence": report.confidence,
            "factors":    report.factors,
        }
        event_name = report.event_name or (
            f"{report.signal}_SIGNAL" if report.signal != "NEUTRAL" else "ANALYSIS"
        )
        self._pub.info(event_name, report.summary, payload)

    def _factor(
        self,
        name:    str,
        value:   str,
        verdict: str,        # "SUPPORTS" | "OPPOSES" | "NEUTRAL"
        detail:  str = "",
    ) -> dict:
        return {"name": name, "value": value, "verdict": verdict, "detail": detail}
