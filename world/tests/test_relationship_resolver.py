"""Phase W5: relationship_resolver — pure functions over a WorldState."""
from world.runtime.models import AgentState, MissionState, RoomState, WorldState
from world.runtime.relationship_resolver import (
    resolve_active_meetings,
    resolve_agent_locations,
    resolve_department_ownership,
    resolve_mission_owners,
    resolve_room_occupants,
)


def _sample_state():
    rooms = (
        RoomState(room_id="ai-council", name="AI Department",
                   occupant_agent_ids=("chameleon", "oracle"),
                   active_mission_ids=("m1",), is_active=True),
        RoomState(room_id="ceo-tower", name="CEO Office",
                   occupant_agent_ids=("primus",), is_active=False),
    )
    agents = (
        AgentState(agent_id="chameleon", agent_ref="CHAMELEON", current_room_id="ai-council"),
        AgentState(agent_id="oracle", agent_ref="ORACLE", current_room_id="ai-council"),
        AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ceo-tower"),
    )
    missions = (MissionState(mission_id="m1", title="Strategize", district="ai-council", status="active"),)
    return WorldState(rooms=rooms, agents=agents, missions=missions)


def test_resolve_agent_locations():
    locations = resolve_agent_locations(_sample_state())
    assert locations["primus"] == "ceo-tower"
    assert locations["chameleon"] == "ai-council"


def test_resolve_room_occupants():
    occupants = resolve_room_occupants(_sample_state())
    assert set(occupants["ai-council"]) == {"chameleon", "oracle"}
    assert occupants["ceo-tower"] == ("primus",)


def test_resolve_mission_owners():
    owners = resolve_mission_owners(_sample_state())
    assert set(owners["m1"]) == {"chameleon", "oracle"}


def test_resolve_mission_owners_empty_when_no_one_present():
    state = WorldState(
        rooms=(RoomState(room_id="ai-council", name="AI Department"),),
        missions=(MissionState(mission_id="m2", title="X", district="ai-council", status="proposed"),),
    )
    owners = resolve_mission_owners(state)
    assert owners["m2"] == ()


def test_resolve_active_meetings_requires_two_agents_and_a_mission():
    meetings = resolve_active_meetings(_sample_state())
    assert meetings == ("ai-council",)


def test_resolve_active_meetings_excludes_single_occupant_room():
    state = _sample_state()
    meetings = resolve_active_meetings(state)
    assert "ceo-tower" not in meetings


def test_resolve_department_ownership_reads_real_district_definitions():
    ownership = resolve_department_ownership()
    assert ownership["ceo-tower"] == ("PRIMUS",)
    assert "ai-council" in ownership
