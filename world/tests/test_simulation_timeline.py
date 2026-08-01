"""Phase W7, Part F: Timeline."""
from world.simulation.models import SimulationState, SimulationTick
from world.simulation.timeline import Timeline


def _state(tick_number: int) -> SimulationState:
    return SimulationState(tick=SimulationTick(tick_number=tick_number, simulated_seconds=float(tick_number),
                                                world_sequence=tick_number))


def test_record_while_playing_follows_the_cursor():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.record(_state(2))
    assert timeline.current().tick.tick_number == 2


def test_pause_freezes_cursor_while_new_ticks_still_record():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.pause()
    timeline.record(_state(2))
    timeline.record(_state(3))
    assert timeline.current().tick.tick_number == 1
    assert len(timeline) == 3


def test_resume_jumps_cursor_to_latest():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.pause()
    timeline.record(_state(2))
    timeline.resume()
    assert timeline.current().tick.tick_number == 2


def test_play_resets_cursor_to_beginning():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.record(_state(2))
    timeline.play()
    assert timeline.current().tick.tick_number == 1


def test_seek_to_known_tick():
    timeline = Timeline()
    for i in range(1, 6):
        timeline.record(_state(i))
    found = timeline.seek(3)
    assert found.tick.tick_number == 3
    assert timeline.current().tick.tick_number == 3
    assert timeline.is_playing() is False


def test_seek_to_unknown_tick_returns_none_and_does_not_move_cursor():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.record(_state(2))
    before = timeline.current()
    result = timeline.seek(999)
    assert result is None
    assert timeline.current() is before


def test_history_window_drops_oldest_entries():
    timeline = Timeline(history_window=3)
    for i in range(1, 6):
        timeline.record(_state(i))
    assert len(timeline) == 3
    assert timeline.seek(1) is None  # dropped
    assert timeline.seek(2) is None  # dropped
    assert timeline.seek(3) is not None
    assert timeline.seek(5) is not None


def test_reset_clears_everything():
    timeline = Timeline()
    timeline.record(_state(1))
    timeline.reset()
    assert len(timeline) == 0
    assert timeline.current() is None


def test_empty_timeline_current_is_none():
    timeline = Timeline()
    assert timeline.current() is None
