"""Phase W5, Part H: world.runtime.api — the only public functions."""
from world.runtime import api


def test_get_world_state_returns_a_world_state():
    state = api.get_world_state()
    assert len(state.rooms) == 17
    assert len(state.agents) == 16


def test_get_room_state_known_room():
    room = api.get_room_state("ceo-tower")
    assert room is not None
    assert room.room_id == "ceo-tower"


def test_get_room_state_unknown_room_returns_none():
    assert api.get_room_state("not-a-real-room") is None


def test_get_agent_state_known_agent():
    agent = api.get_agent_state("primus")
    assert agent is not None
    assert agent.agent_ref == "PRIMUS"


def test_get_agent_state_unknown_agent_returns_none():
    assert api.get_agent_state("not-a-real-agent") is None


def test_refresh_world_forces_new_sequence():
    first = api.get_world_state()
    second = api.refresh_world()
    assert second.sequence > first.sequence


def test_get_world_statistics_reports_room_and_agent_counts():
    stats = api.get_world_statistics()
    assert stats.active_rooms + stats.inactive_rooms == 17
    assert stats.active_agents + stats.inactive_agents == 16
    assert stats.update_frequency_per_second >= 0.0
