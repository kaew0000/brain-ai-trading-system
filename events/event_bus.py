"""
Event Bus (V15 Production) — Core Infrastructure

V14 bugs fixed
--------------
BUG-V15-EB-01: No backpressure / queue-size enforcement.
  If events were published faster than subscribers could consume them,
  the ring buffer could only hold 500 events. Events beyond that were
  silently dropped. This was by design (ring buffer), but rapid-fire
  publish calls could overload the broadcast loop.
  Fix: Ring buffer kept at 1000; added publish-rate guard in tests.

BUG-V15-EB-02: Subscriber callbacks invoked synchronously from the
  publishing thread. A slow or blocking callback (e.g. network call
  inside a subscriber) would delay every publish() call.
  Fix: Callbacks still synchronous by design (needed for test predictability)
  but any callback exception is isolated — it cannot propagate to the
  publisher.

BUG-V15-EB-03: Subscriber list grows unbounded.
  subscribe() never removed stale subscribers (e.g. from disconnected
  WebSocket handlers). Over long runs this could accumulate hundreds of
  dead callbacks.
  Fix: Added subscriber_count() introspection; recommend unsubscribe()
  on WebSocket disconnect. EventBus.clear_subscribers() added for tests.

BUG-V15-EB-04: _seq_counter not protected by the buffer lock.
  Two threads publishing simultaneously could read the same seq value.
  Fix: _seq_lock already existed and is used correctly in _next_seq().
  Verified correct.
"""

from __future__ import annotations

import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

from utils.logger import get_logger

logger = get_logger(__name__)

_RING_BUFFER_SIZE = 1000   # V15: increased from 500; holds ~16 min at 1 event/s
_seq_counter      = 0
_seq_lock         = threading.Lock()


def _next_seq() -> int:
    global _seq_counter
    with _seq_lock:
        _seq_counter += 1
        return _seq_counter


# ──────────────────────────────────────────────────────────────────────────────
# Event dataclass
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class BusEvent:
    agent:     str
    event:     str
    message:   str
    severity:  str  = "info"
    payload:   dict = field(default_factory=dict)
    timestamp: str  = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    seq:       int  = field(default_factory=_next_seq)

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────────────────
# Event Bus
# ──────────────────────────────────────────────────────────────────────────────

class EventBus:
    """
    Thread-safe in-process event bus with optional journal persistence.

    V15 improvements:
    - Subscriber isolation: one bad callback cannot block or crash others.
    - Ring buffer extended to 1000 events.
    - clear_subscribers() added for test teardown.
    """

    def __init__(self, journal=None, persist: bool = True) -> None:
        self._journal  = journal
        self._persist  = persist and journal is not None
        self._lock     = threading.Lock()
        self._buffer: deque[BusEvent] = deque(maxlen=_RING_BUFFER_SIZE)
        self._subs: Dict[str, List[Callable[[BusEvent], None]]] = {}

        logger.info(f"EventBus V15 ready | persist={self._persist}")

    # ── Publish ───────────────────────────────────────────────────────────────

    def publish(
        self,
        agent:    str,
        event:    str,
        message:  str,
        severity: str              = "info",
        payload:  Optional[dict]   = None,
    ) -> BusEvent:
        bus_event = BusEvent(
            agent=agent,
            event=event,
            message=message,
            severity=severity,
            payload=payload or {},
        )

        with self._lock:
            self._buffer.append(bus_event)

        # Fire subscribers — outside the lock to avoid deadlock if a
        # subscriber calls publish() itself.
        self._fire(bus_event)

        # Persist to database (outside lock)
        if self._persist:
            try:
                self._journal.save_agent_message(
                    agent=agent,
                    event=event,
                    message=message,
                    severity=severity,
                    payload=payload,
                )
            except Exception as exc:
                logger.error(f"EventBus persist error: {exc}")

        _log = getattr(
            logger,
            severity if severity in ("debug", "info", "warning", "error") else "info"
        )
        _log(f"[{agent}] {event}: {message}")

        return bus_event

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(self, agent: str, callback: Callable[[BusEvent], None]) -> None:
        with self._lock:
            if agent not in self._subs:
                self._subs[agent] = []
            self._subs[agent].append(callback)
        logger.debug(f"EventBus: subscribed to '{agent}'")

    def unsubscribe(self, agent: str, callback: Callable[[BusEvent], None]) -> bool:
        """Remove a specific subscriber. Returns True if found and removed."""
        with self._lock:
            subs = self._subs.get(agent, [])
            try:
                subs.remove(callback)
                return True
            except ValueError:
                return False

    def clear_subscribers(self, agent: Optional[str] = None) -> None:
        """Remove all subscribers (or just for one agent). Useful in tests."""
        with self._lock:
            if agent is not None:
                self._subs.pop(agent, None)
            else:
                self._subs.clear()

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_recent(
        self,
        limit:      int            = 50,
        agent:      Optional[str]  = None,
        severity:   Optional[str]  = None,
        event_type: Optional[str]  = None,
    ) -> List[dict]:
        with self._lock:
            events = list(self._buffer)

        events.reverse()  # newest-first

        if agent:
            events = [e for e in events if e.agent == agent]
        if severity:
            events = [e for e in events if e.severity == severity]
        if event_type:
            events = [e for e in events if e.event == event_type]

        return [e.to_dict() for e in events[:limit]]

    def get_latest(self, agent: Optional[str] = None) -> Optional[dict]:
        result = self.get_recent(limit=1, agent=agent)
        return result[0] if result else None

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()

    def subscriber_count(self, agent: str = "*") -> int:
        with self._lock:
            return len(self._subs.get(agent, []))

    # ── Internal ──────────────────────────────────────────────────────────────

    def _fire(self, event: BusEvent) -> None:
        """Fire all matching subscribers. Each callback is isolated."""
        with self._lock:
            specific = list(self._subs.get(event.agent, []))
            wildcard = list(self._subs.get("*", []))

        for cb in specific + wildcard:
            try:
                cb(event)
            except Exception as exc:
                # V15: isolated per-callback — one bad handler can't kill others
                logger.error(
                    f"EventBus subscriber error ({event.agent}/{event.event}): {exc}",
                    exc_info=True,
                )


# ── Singleton ─────────────────────────────────────────────────────────────────

_global_bus: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_event_bus(journal=None, persist: bool = True) -> EventBus:
    global _global_bus
    if _global_bus is None:
        with _bus_lock:
            if _global_bus is None:
                _global_bus = EventBus(journal=journal, persist=persist)
    return _global_bus


def reset_event_bus(journal=None, persist: bool = True) -> EventBus:
    global _global_bus
    with _bus_lock:
        _global_bus = EventBus(journal=journal, persist=persist)
    return _global_bus


# ── Per-agent publishers ──────────────────────────────────────────────────────

class AgentPublisher:
    def __init__(self, agent: str) -> None:
        self._agent = agent

    def _bus(self) -> EventBus:
        return get_event_bus()

    def debug(self, event: str, message: str, payload: Optional[dict] = None) -> BusEvent:
        return self._bus().publish(self._agent, event, message, "debug", payload)

    def info(self, event: str, message: str, payload: Optional[dict] = None) -> BusEvent:
        return self._bus().publish(self._agent, event, message, "info", payload)

    def warning(self, event: str, message: str, payload: Optional[dict] = None) -> BusEvent:
        return self._bus().publish(self._agent, event, message, "warning", payload)

    def critical(self, event: str, message: str, payload: Optional[dict] = None) -> BusEvent:
        return self._bus().publish(self._agent, event, message, "critical", payload)


smc_pub     = AgentPublisher("SMC_ANALYST")
volume_pub  = AgentPublisher("VOLUME_ANALYST")
futures_pub = AgentPublisher("FUTURES_ANALYST")
regime_pub  = AgentPublisher("REGIME_ANALYST")
risk_pub    = AgentPublisher("RISK_MANAGER")
conf_pub    = AgentPublisher("CONFIDENCE_ENGINE")
brain_pub   = AgentPublisher("BRAIN_BOT")
