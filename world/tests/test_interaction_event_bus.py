"""Phase W9: EventBus — SelectionChanged, HoverChanged, CameraMoved,
TimelineChanged, SimulationPaused, SimulationResumed."""

import pytest

from world.interaction.interaction_events import EVENT_TYPES, EventBus


def test_all_six_brief_event_types_are_registered():
    expected = {
        "SelectionChanged", "HoverChanged", "CameraMoved",
        "TimelineChanged", "SimulationPaused", "SimulationResumed",
    }
    assert set(EVENT_TYPES) == expected


def test_publish_calls_subscribed_handlers():
    bus = EventBus()
    received = []
    bus.subscribe("SelectionChanged", received.append)
    bus.publish("SelectionChanged", {"kind": "room", "targetId": "risk-fortress"})
    assert len(received) == 1
    assert received[0].payload == {"kind": "room", "targetId": "risk-fortress"}


def test_publish_unknown_event_type_raises():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.publish("NotARealEvent", {})


def test_subscribe_unknown_event_type_raises():
    bus = EventBus()
    with pytest.raises(ValueError):
        bus.subscribe("NotARealEvent", lambda e: None)


def test_history_filters_by_event_type():
    bus = EventBus()
    bus.publish("CameraMoved", {})
    bus.publish("SimulationPaused", {})
    bus.publish("CameraMoved", {})
    assert len(bus.history("CameraMoved")) == 2
    assert len(bus.history("SimulationPaused")) == 1
    assert len(bus.history()) == 3


def test_clear_history():
    bus = EventBus()
    bus.publish("CameraMoved", {})
    bus.clear_history()
    assert bus.history() == ()
