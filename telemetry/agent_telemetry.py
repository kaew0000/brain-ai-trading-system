"""
telemetry/agent_telemetry.py
=============================
Agent Telemetry Layer (v14 Phase 2)

Every agent run (BaseAgent.run() and CEOAgent.decide()) is wrapped with
timing + status capture and reported into a single thread-safe registry.

Schema (exact, per spec)
-------------------------
{
  "agent":       str,
  "status":      "OK" | "ERROR" | "IDLE",
  "confidence":  float 0-100,
  "last_signal": str,
  "latency_ms":  float,
  "decision":    str,
  "timestamp":   str (ISO 8601)
}

Additional fields (non-breaking extras, used by the dashboard but not
required by the spec): "uptime_s", "run_count", "error_count".

Design
------
- Pure stdlib (no new dependencies)
- Thread-safe via a single lock (same pattern as EventBus)
- Read-mostly workload — snapshot() is O(n_agents), cheap to poll every 1s
- Does NOT replace EventBus; this is a fast, structured "current state"
  view, whereas EventBus is an append-only log of everything that happened.

Usage
-----
from telemetry.agent_telemetry import get_telemetry_registry

registry = get_telemetry_registry()
registry.record(agent="SMC_ANALYST", status="OK", confidence=78.0,
                 last_signal="LONG", latency_ms=12.4, decision="BOS bullish M15")

snapshot = registry.snapshot()              # all agents
one      = registry.get("SMC_ANALYST")      # single agent
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Dict, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

VALID_STATUSES = ("OK", "ERROR", "IDLE", "RUNNING")


@dataclass
class AgentTelemetry:
    """Structured telemetry snapshot for a single agent."""

    agent:       str
    status:      str   = "IDLE"
    confidence:  float = 0.0
    last_signal: str   = ""
    latency_ms:  float = 0.0
    decision:    str   = ""
    timestamp:   str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # Extra (non-spec) fields — additive, dashboard-only
    uptime_s:    float = 0.0
    run_count:   int   = 0
    error_count: int   = 0

    def to_dict(self) -> dict:
        return asdict(self)

    def to_spec_dict(self) -> dict:
        """Exact 7-field schema as specified in the v14 brief (no extras)."""
        return {
            "agent":       self.agent,
            "status":      self.status,
            "confidence":  self.confidence,
            "last_signal": self.last_signal,
            "latency_ms":  self.latency_ms,
            "decision":    self.decision,
            "timestamp":   self.timestamp,
        }


class TelemetryRegistry:
    """
    Thread-safe in-memory registry of the latest AgentTelemetry per agent.

    One process-wide singleton (see get_telemetry_registry()).
    """

    def __init__(self) -> None:
        self._lock:      threading.Lock = threading.Lock()
        self._entries:   Dict[str, AgentTelemetry] = {}
        self._first_seen: Dict[str, float] = {}   # agent -> perf_counter() at first record

    def record(
        self,
        agent:       str,
        status:      str,
        confidence:  float = 0.0,
        last_signal: str   = "",
        latency_ms:  float = 0.0,
        decision:    str   = "",
    ) -> AgentTelemetry:
        """
        Record a telemetry update for one agent. Thread-safe.

        Called by BaseAgent.run() and CEOAgent.decide() after every cycle.
        """
        if status not in VALID_STATUSES:
            status = "OK"  # defensive default — never raise on bad input

        now_wall = datetime.now(timezone.utc).isoformat()

        with self._lock:
            if agent not in self._first_seen:
                self._first_seen[agent] = time.perf_counter()

            prev = self._entries.get(agent)
            run_count   = (prev.run_count if prev else 0) + 1
            error_count = (prev.error_count if prev else 0) + (1 if status == "ERROR" else 0)
            uptime_s    = round(time.perf_counter() - self._first_seen[agent], 2)

            entry = AgentTelemetry(
                agent=agent,
                status=status,
                confidence=round(float(confidence), 2),
                last_signal=last_signal,
                latency_ms=round(float(latency_ms), 2),
                decision=decision[:200] if decision else "",
                timestamp=now_wall,
                uptime_s=uptime_s,
                run_count=run_count,
                error_count=error_count,
            )
            self._entries[agent] = entry

        return entry

    def get(self, agent: str) -> Optional[AgentTelemetry]:
        with self._lock:
            return self._entries.get(agent)

    def snapshot(self) -> Dict[str, dict]:
        """Return {agent_name: telemetry_dict} for every known agent."""
        with self._lock:
            return {name: e.to_dict() for name, e in self._entries.items()}

    def snapshot_spec(self) -> Dict[str, dict]:
        """Same as snapshot() but restricted to the exact 7-field spec schema."""
        with self._lock:
            return {name: e.to_spec_dict() for name, e in self._entries.items()}

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._first_seen.clear()


# ── Singleton accessor (mirrors events.event_bus pattern) ─────────────────────

_global_registry: Optional[TelemetryRegistry] = None
_registry_lock = threading.Lock()


def get_telemetry_registry() -> TelemetryRegistry:
    global _global_registry
    if _global_registry is None:
        with _registry_lock:
            if _global_registry is None:
                _global_registry = TelemetryRegistry()
                logger.info("TelemetryRegistry ready")
    return _global_registry


def reset_telemetry_registry() -> TelemetryRegistry:
    """Replace the global singleton (useful in tests)."""
    global _global_registry
    with _registry_lock:
        _global_registry = TelemetryRegistry()
    return _global_registry


class telemetry_timer:
    """
    Context manager that measures wall-clock latency in milliseconds.

    `latency_ms` is a LIVE property — it returns the correct elapsed time
    whether read after the `with` block exits OR from inside an `except`
    clause nested within the `with` body (i.e. before __exit__ has run).
    This avoids a subtle bug where reading a frozen value before __exit__
    always returns 0.0.

    Usage:
        with telemetry_timer() as t:
            try:
                do_work()
            except Exception:
                record_error(latency_ms=t.latency_ms)   # correct, live value
                raise
        record_ok(latency_ms=t.latency_ms)               # also correct
    """

    def __enter__(self) -> "telemetry_timer":
        self._start = time.perf_counter()
        self._frozen_ms: Optional[float] = None
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        self._frozen_ms = round((time.perf_counter() - self._start) * 1000, 2)
        return False  # never suppress exceptions

    @property
    def latency_ms(self) -> float:
        if self._frozen_ms is not None:
            return self._frozen_ms
        return round((time.perf_counter() - self._start) * 1000, 2)
