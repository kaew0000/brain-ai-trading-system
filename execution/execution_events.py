"""
execution/execution_events.py — V16 Phase 2E: Execution Wiring & Live
Orchestrator

Deliberately NOT a second pub/sub mechanism. events/event_bus.py already
provides a thread-safe, ring-buffered, subscriber-isolated EventBus
(BusEvent, get_event_bus(), AgentPublisher) that every other subsystem in
this codebase (agents/, telemetry/, reasoning/) already publishes
through. Duplicating that here — a second queue, a second subscriber
list — would be exactly the kind of parallel implementation
CLAUDE.md/the phase brief rules out.

This module instead defines the *execution-specific vocabulary* on top
of the existing bus:
  - EXECUTION_AGENT: the fixed `agent` name ExecutionOrchestrator
    publishes under, so subscribers (tests, api/portfolio_ws.py) can
    filter get_event_bus().get_recent(agent=EXECUTION_AGENT) without
    guessing a string.
  - ExecutionEventType: the closed set of event names the phase brief
    requires (execution_started/completed/failed/cancelled/
    metrics_updated) — matches the `event` field of a BusEvent.
  - publish_execution_event(): the one call site every execution-event
    publish in this phase goes through, so the payload shape
    (execution_id, decision_id, symbol, ...) is guaranteed consistent
    without every call site re-typing the same dict keys.
"""
from __future__ import annotations

from enum import Enum

from events.event_bus import BusEvent, EventBus, get_event_bus

EXECUTION_AGENT = "EXECUTION_ORCHESTRATOR"


class ExecutionEventType(str, Enum):
    """The exact event-name vocabulary the Phase 2E brief specifies for
    the WebSocket layer. Values (not just names) are what actually reach
    subscribers/clients, so they are the wire contract — do not rename
    without treating it as a breaking API change."""

    STARTED          = "execution_started"
    COMPLETED        = "execution_completed"
    FAILED           = "execution_failed"
    CANCELLED        = "execution_cancelled"
    METRICS_UPDATED  = "execution_metrics_updated"


def publish_execution_event(
    event_type: ExecutionEventType,
    *,
    execution_id: str,
    symbol: str | None = None,
    decision_id: str | None = None,
    message: str = "",
    severity: str = "info",
    payload: dict | None = None,
    bus: EventBus | None = None,
) -> BusEvent:
    """Publish one execution-lifecycle event through the existing
    EventBus. Returns the BusEvent so callers/tests can assert on
    `.seq` (used by api/portfolio_ws.py's dedup-by-seq relay — see that
    module's check_and_broadcast() additions).

    `bus` is accepted (defaults to the process-wide get_event_bus()
    singleton) purely so tests can inject an isolated EventBus instance
    instead of mutating global state — mirrors how ExecutionOrchestrator
    itself accepts dependencies rather than reaching for globals.
    """
    full_payload = {
        "execution_id": execution_id,
        "decision_id":  decision_id,
        "symbol":       symbol,
        **(payload or {}),
    }
    event_bus = bus or get_event_bus()
    return event_bus.publish(
        agent=EXECUTION_AGENT,
        event=event_type.value,
        message=message or event_type.value,
        severity=severity,
        payload=full_payload,
    )
