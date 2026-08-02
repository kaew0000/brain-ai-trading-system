"""Phase W9: TimelineController."""

import pytest

from world.interaction.timeline_controller import TimelineController, UnknownEventError
from world.simulation.models import EventDescriptor, SimulationState, SimulationTick
from world.simulation.timeline import Timeline


def _state(tick_number, events=()):
    return SimulationState(
        tick=SimulationTick(tick_number=tick_number, simulated_seconds=float(tick_number), world_sequence=tick_number),
        events=events,
    )


def _populated_timeline():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.record(_state(2, events=(EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="r1"),)))
    timeline.record(_state(3))
    return timeline


def _controller():
    timeline = _populated_timeline()
    return TimelineController(get_timeline=lambda: timeline), timeline


def test_current_returns_latest_state():
    controller, _ = _controller()
    assert controller.current().tick.tick_number == 3


def test_seek_moves_to_the_requested_tick():
    controller, _ = _controller()
    state = controller.seek(1)
    assert state.tick.tick_number == 1
    assert controller.current().tick.tick_number == 1


def test_seek_unknown_tick_returns_none():
    controller, _ = _controller()
    assert controller.seek(999) is None


def test_jump_to_event_finds_the_tick_that_produced_it():
    controller, _ = _controller()
    state = controller.jump_to_event("evt-1")
    assert state.tick.tick_number == 2
    assert controller.current().tick.tick_number == 2


def test_jump_to_unknown_event_raises():
    controller, _ = _controller()
    with pytest.raises(UnknownEventError):
        controller.jump_to_event("nonexistent-evt")


def test_pause_resume_play_delegate_to_timeline():
    controller, timeline = _controller()
    controller.pause()
    assert timeline.is_playing() is False
    controller.resume()
    assert timeline.is_playing() is True


def test_length_matches_timeline_length():
    controller, _ = _controller()
    assert controller.length() == 3
