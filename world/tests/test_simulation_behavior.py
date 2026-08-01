"""Phase W7, Part B: character behaviour — each precedence rule in
`behavior.determine_behavior`'s own documented order, exercised in
isolation."""
from world.runtime.models import AgentState, EventState, MissionState, RoomState, WorldState
from world.simulation.behavior import determine_behavior
from world.simulation.models import Position
from world.simulation.movement import MovementController


def _state_with_agent(room_id="ceo-tower", status="idle", is_active=False, **room_kwargs):
    agents = (AgentState(agent_id="primus", agent_ref="PRIMUS",
                          current_room_id=room_id, status=status, is_active=is_active),)
    rooms = (RoomState(room_id=room_id, name="CEO Office", **room_kwargs),)
    return agents, rooms


def test_idle_when_nothing_else_applies():
    agents, rooms = _state_with_agent()
    state = WorldState(agents=agents, rooms=rooms)
    movement = MovementController()
    movement.place("primus", Position(0, 0), "ceo-tower")
    assert determine_behavior("primus", state, movement) == "idle"


def test_working_when_agent_status_is_working():
    agents, rooms = _state_with_agent(status="working", is_active=True)
    state = WorldState(agents=agents, rooms=rooms)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "working"


def test_emergency_overrides_working_on_critical_event():
    agents, rooms = _state_with_agent(status="working", is_active=True)
    events = (EventState(event_id="e1", timestamp="t", event_type="risk_alert",
                          district="ceo-tower", severity="critical"),)
    state = WorldState(agents=agents, rooms=rooms, events=events)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "emergency"


def test_meeting_when_room_has_two_occupants_and_active_mission():
    agents = (
        AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ai-council"),
        AgentState(agent_id="oracle", agent_ref="ORACLE", current_room_id="ai-council"),
    )
    rooms = (RoomState(room_id="ai-council", name="AI Department",
                        occupant_agent_ids=("primus", "oracle"),
                        active_mission_ids=("m1",)),)
    missions = (MissionState(mission_id="m1", title="X", district="ai-council", status="active"),)
    state = WorldState(agents=agents, rooms=rooms, missions=missions)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "meeting"


def test_meeting_takes_precedence_over_working():
    agents = (
        AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ai-council", status="working"),
        AgentState(agent_id="oracle", agent_ref="ORACLE", current_room_id="ai-council"),
    )
    rooms = (RoomState(room_id="ai-council", name="AI Department",
                        occupant_agent_ids=("primus", "oracle"), active_mission_ids=("m1",)),)
    missions = (MissionState(mission_id="m1", title="X", district="ai-council", status="active"),)
    state = WorldState(agents=agents, rooms=rooms, missions=missions)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "meeting"


def test_celebration_on_success_growth_event():
    agents, rooms = _state_with_agent()
    events = (EventState(event_id="e1", timestamp="t", event_type="portfolio_growth",
                          district="ceo-tower", severity="success"),)
    state = WorldState(agents=agents, rooms=rooms, events=events)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "celebration"


def test_resting_in_recovery_center_when_inactive():
    agents, rooms = _state_with_agent(room_id="recovery-center", is_active=False)
    state = WorldState(agents=agents, rooms=rooms)
    movement = MovementController()
    assert determine_behavior("primus", state, movement) == "resting"


def test_walking_when_movement_in_progress():
    agents, rooms = _state_with_agent()
    state = WorldState(agents=agents, rooms=rooms)
    movement = MovementController()
    movement.place("primus", Position(0.0, 0.0), "ceo-tower")
    movement.set_destination("primus", Position(1.0, 0.0), "ceo-tower")
    assert determine_behavior("primus", state, movement) == "walking"


def test_unknown_agent_defaults_to_idle():
    state = WorldState()
    movement = MovementController()
    assert determine_behavior("ghost", state, movement) == "idle"
