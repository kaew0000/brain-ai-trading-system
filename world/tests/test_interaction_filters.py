"""Phase W9: filters."""

from world.interaction.filters import (
    filter_agents_by_state,
    filter_alerts,
    filter_by_room_type,
    filter_meetings,
    filter_rooms_by_department,
    filter_rooms_by_simulation_state,
)
from world.runtime.models import AgentState, RoomState, WorldState
from world.simulation.models import RoomActivityState, SimulationState, SimulationTick


def _fake_world_state():
    return WorldState(
        rooms=(
            RoomState(room_id="risk-fortress", name="Risk Department", occupant_agent_ids=("a1", "a2"),
                      active_mission_ids=("m1",)),
            RoomState(room_id="lobby", name="Lobby", occupant_agent_ids=()),
        ),
        agents=(
            AgentState(agent_id="a1", agent_ref="A1", current_room_id="risk-fortress", status="working"),
            AgentState(agent_id="a2", agent_ref="A2", current_room_id="risk-fortress", status="idle"),
        ),
    )


def _fake_sim_state():
    return SimulationState(
        tick=SimulationTick(tick_number=1, simulated_seconds=1.0, world_sequence=1),
        rooms=(
            RoomActivityState(room_id="risk-fortress", activity="critical", occupant_count=2),
            RoomActivityState(room_id="lobby", activity="quiet", occupant_count=0),
        ),
    )


def test_filter_rooms_by_department():
    state = _fake_world_state()
    result = filter_rooms_by_department(state, ("risk-fortress",))
    assert [r.room_id for r in result] == ["risk-fortress"]


def test_filter_by_room_type_department():
    state = _fake_world_state()
    result = filter_by_room_type(state, "department")
    assert [r.room_id for r in result] == ["risk-fortress"]


def test_filter_by_room_type_circulation():
    state = _fake_world_state()
    result = filter_by_room_type(state, "circulation")
    assert [r.room_id for r in result] == ["lobby"]


def test_filter_by_room_type_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        filter_by_room_type(_fake_world_state(), "spaceship")


def test_filter_agents_by_state():
    state = _fake_world_state()
    working = filter_agents_by_state(state, "working")
    assert [a.agent_id for a in working] == ["a1"]


def test_filter_rooms_by_simulation_state():
    sim_state = _fake_sim_state()
    critical = filter_rooms_by_simulation_state(sim_state, "critical")
    assert [r.room_id for r in critical] == ["risk-fortress"]


def test_filter_alerts_includes_critical_and_alert():
    sim_state = _fake_sim_state()
    alerts = filter_alerts(sim_state)
    assert [r.room_id for r in alerts] == ["risk-fortress"]


def test_filter_meetings_reuses_relationship_resolver():
    state = _fake_world_state()
    # risk-fortress has 2 occupants + 1 active mission -> counts as a meeting
    # per world.runtime.relationship_resolver.resolve_active_meetings
    meetings = filter_meetings(state)
    assert "risk-fortress" in meetings
