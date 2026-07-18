"""
reasoning/reasoning_stream.py
==============================
Agent Reasoning Stream (v14 Phase 2.5)

Distinct from telemetry/agent_telemetry.py:
  - TelemetryRegistry  → "How is the agent doing?" (status/latency/uptime — operational)
  - ReasoningStream     → "What is the agent thinking?" (thought/reasoning/decision — cognitive)

This is the data source for the future Agent Debate Room dashboard page,
where each agent's narrative reasoning is displayed side-by-side so a
human can follow WHY the CEO reached its final decision.

Schema (exact, per spec)
-------------------------
{
  "agent":      str,
  "thought":    str,   # short one-line internal monologue
  "reasoning":  str,   # fuller narrative explaining the thought
  "decision":   str,   # concrete output (e.g. "LONG", "NEUTRAL")
  "confidence": float, # 0-100
  "timestamp":  str    # ISO 8601
}

Design
------
- Pure stdlib, thread-safe (mirrors events/event_bus.py's proven pattern)
- Ring buffer (last N entries) + a "latest per agent" index for O(1) lookup
- Read-mostly workload — safe to poll every 1s from the broadcast loop

Usage
-----
from reasoning.reasoning_stream import get_reasoning_stream

stream = get_reasoning_stream()
stream.record(
    agent="SMC_ANALYST",
    thought="Bullish BOS on M15, confidence rising",
    reasoning="BOS: Bullish structure break supports LONG. FVG: unmitigated gap "
              "at 67200 supports LONG. OB: order block respected supports LONG.",
    decision="LONG",
    confidence=82.0,
)

recent = stream.get_recent(limit=50)             # all agents, newest-first
recent_smc = stream.get_recent(agent="SMC_ANALYST", limit=10)
latest = stream.get_latest(agent="CEO_AGENT")
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_RING_BUFFER_SIZE = 500


@dataclass
class ReasoningEntry:
    """Structured reasoning trace for a single agent run."""

    agent:      str
    thought:    str
    reasoning:  str
    decision:   str
    confidence: float
    timestamp:  str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return asdict(self)


class ReasoningStream:
    """
    Thread-safe ring buffer of ReasoningEntry, with a per-agent "latest" index.

    One process-wide singleton (see get_reasoning_stream()).
    """

    def __init__(self) -> None:
        self._lock:   threading.Lock = threading.Lock()
        self._buffer: Deque[ReasoningEntry] = deque(maxlen=_RING_BUFFER_SIZE)
        self._latest: Dict[str, ReasoningEntry] = {}

    def record(
        self,
        agent:      str,
        thought:    str,
        reasoning:  str,
        decision:   str,
        confidence: float = 0.0,
    ) -> ReasoningEntry:
        """Record a new reasoning entry for an agent. Thread-safe."""
        entry = ReasoningEntry(
            agent=agent,
            thought=thought[:300] if thought else "",
            reasoning=reasoning[:2000] if reasoning else "",
            decision=decision or "",
            confidence=round(float(confidence), 2),
        )
        with self._lock:
            self._buffer.append(entry)
            self._latest[agent] = entry
        return entry

    def get_recent(self, limit: int = 50, agent: Optional[str] = None) -> List[dict]:
        """Return recent entries, newest-first. Optionally filtered by agent."""
        with self._lock:
            entries = list(self._buffer)
        entries.reverse()
        if agent:
            entries = [e for e in entries if e.agent == agent]
        return [e.to_dict() for e in entries[:limit]]

    def get_latest(self, agent: Optional[str] = None) -> Optional[dict]:
        """Return the single most recent entry overall, or for one agent."""
        with self._lock:
            if agent:
                entry = self._latest.get(agent)
                return entry.to_dict() if entry else None
            if not self._buffer:
                return None
            return self._buffer[-1].to_dict()

    def get_latest_all(self) -> Dict[str, dict]:
        """Return {agent_name: latest_entry_dict} for every known agent."""
        with self._lock:
            return {name: e.to_dict() for name, e in self._latest.items()}

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
            self._latest.clear()


# ── Singleton accessor (mirrors events.event_bus pattern) ─────────────────────

_global_stream: Optional[ReasoningStream] = None
_stream_lock = threading.Lock()


def get_reasoning_stream() -> ReasoningStream:
    global _global_stream
    if _global_stream is None:
        with _stream_lock:
            if _global_stream is None:
                _global_stream = ReasoningStream()
                logger.info("ReasoningStream ready")
    return _global_stream


def reset_reasoning_stream() -> ReasoningStream:
    """Replace the global singleton (useful in tests)."""
    global _global_stream
    with _stream_lock:
        _global_stream = ReasoningStream()
    return _global_stream
