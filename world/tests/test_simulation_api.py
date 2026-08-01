"""Phase W7, Part G: world.simulation.api — the only public functions."""
from world.simulation import api


def test_get_simulation_state_returns_a_state_with_real_counts():
    state = api.get_simulation_state()
    assert len(state.characters) == 16
    assert len(state.rooms) == 17


def test_get_character_activity_known_agent():
    activity = api.get_character_activity("primus")
    assert activity is not None
    assert activity.agent_ref == "PRIMUS"


def test_get_character_activity_unknown_agent_returns_none():
    assert api.get_character_activity("not-a-real-agent") is None


def test_get_room_activity_known_room():
    activity = api.get_room_activity("ceo-tower")
    assert activity is not None
    assert activity.room_id == "ceo-tower"


def test_get_room_activity_unknown_room_returns_none():
    assert api.get_room_activity("not-a-real-room") is None


def test_get_current_events_returns_a_tuple():
    events = api.get_current_events()
    assert isinstance(events, tuple)


def test_step_forces_a_new_tick():
    first = api.get_simulation_state()
    second = api.step()
    assert second.tick.tick_number > first.tick.tick_number


def test_pause_resume_reset_do_not_raise():
    api.pause()
    api.resume()
    api.reset()
    state = api.get_simulation_state()
    assert state.tick.tick_number == 1
