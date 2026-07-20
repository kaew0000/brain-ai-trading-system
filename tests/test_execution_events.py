"""tests/test_execution_events.py — V16 Phase 2E: Execution Wiring & Live Orchestrator"""
from __future__ import annotations

import pytest

from events.event_bus import EventBus
from execution.execution_events import (
    EXECUTION_AGENT,
    ExecutionEventType,
    publish_execution_event,
)

pytestmark = pytest.mark.unit


class TestPublishExecutionEvent:

    def test_publishes_under_fixed_execution_agent(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.STARTED, execution_id="exec-1", symbol="BTCUSDT", bus=bus,
        )
        assert event.agent == EXECUTION_AGENT

    def test_event_name_matches_event_type_value(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.COMPLETED, execution_id="exec-1", bus=bus,
        )
        assert event.event == "execution_completed"

    def test_payload_includes_execution_id_symbol_decision_id(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.FAILED, execution_id="exec-1", symbol="ETHUSDT",
            decision_id="123.0", bus=bus,
        )
        assert event.payload["execution_id"] == "exec-1"
        assert event.payload["symbol"] == "ETHUSDT"
        assert event.payload["decision_id"] == "123.0"

    def test_extra_payload_merged_without_clobbering_standard_keys(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.COMPLETED, execution_id="exec-1", symbol="BTCUSDT",
            payload={"quantity": 1.5}, bus=bus,
        )
        assert event.payload["quantity"] == 1.5
        assert event.payload["symbol"] == "BTCUSDT"

    def test_default_message_falls_back_to_event_type_value(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.CANCELLED, execution_id="exec-1", bus=bus,
        )
        assert event.message == "execution_cancelled"

    def test_explicit_message_overrides_default(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.CANCELLED, execution_id="exec-1", message="no_signal", bus=bus,
        )
        assert event.message == "no_signal"

    def test_severity_is_forwarded(self):
        bus = EventBus(persist=False)
        event = publish_execution_event(
            ExecutionEventType.FAILED, execution_id="exec-1", severity="error", bus=bus,
        )
        assert event.severity == "error"

    def test_subscribers_to_execution_agent_receive_the_event(self):
        bus = EventBus(persist=False)
        received = []
        bus.subscribe(EXECUTION_AGENT, received.append)
        publish_execution_event(ExecutionEventType.STARTED, execution_id="exec-1", bus=bus)
        assert len(received) == 1
        assert received[0].event == "execution_started"

    def test_event_type_values_match_phase_brief_wire_contract(self):
        """These exact strings are the WebSocket wire contract — see
        execution_events.py's module docstring. Renaming any of these
        without treating it as a breaking API change would silently
        break existing clients."""
        assert ExecutionEventType.STARTED.value == "execution_started"
        assert ExecutionEventType.COMPLETED.value == "execution_completed"
        assert ExecutionEventType.FAILED.value == "execution_failed"
        assert ExecutionEventType.CANCELLED.value == "execution_cancelled"
        assert ExecutionEventType.METRICS_UPDATED.value == "execution_metrics_updated"
