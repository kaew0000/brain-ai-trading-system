"""Phase W5: state_validator — each Part G check exercised individually."""
from world.runtime.models import (
    AgentState,
    EventState,
    MissionState,
    NotificationState,
    RoomState,
    WorldState,
)
from world.runtime.state_validator import is_valid, validate


def _base_room(room_id="ceo-tower", **overrides):
    defaults = dict(room_id=room_id, name="CEO Office")
    defaults.update(overrides)
    return RoomState(**defaults)


def test_valid_empty_state_has_no_errors():
    assert validate(WorldState()) == []
    assert is_valid(WorldState())


def test_duplicate_agent_detected():
    agents = (
        AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ceo-tower"),
        AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="ceo-tower"),
    )
    state = WorldState(rooms=(_base_room(),), agents=agents)
    errors = validate(state)
    assert any("Duplicate agent" in e for e in errors)


def test_missing_room_detected():
    agents = (AgentState(agent_id="primus", agent_ref="PRIMUS", current_room_id="nonexistent-room"),)
    state = WorldState(rooms=(_base_room(),), agents=agents)
    errors = validate(state)
    assert any("missing room" in e for e in errors)


def test_invalid_mission_status_detected():
    missions = (MissionState(mission_id="m1", title="X", district="ceo-tower", status="bogus"),)
    state = WorldState(rooms=(_base_room(),), missions=missions)
    errors = validate(state)
    assert any("invalid status" in e for e in errors)


def test_mission_referencing_missing_room_detected():
    missions = (MissionState(mission_id="m1", title="X", district="nowhere", status="active"),)
    state = WorldState(rooms=(_base_room(),), missions=missions)
    errors = validate(state)
    assert any("Mission 'm1' references missing room" in e for e in errors)


def test_broken_room_agent_relationship_detected():
    room = _base_room(occupant_agent_ids=("ghost-agent",))
    state = WorldState(rooms=(room,))
    errors = validate(state)
    assert any("occupant 'ghost-agent'" in e for e in errors)


def test_broken_room_mission_relationship_detected():
    room = _base_room(active_mission_ids=("ghost-mission",))
    state = WorldState(rooms=(room,))
    errors = validate(state)
    assert any("mission 'ghost-mission'" in e for e in errors)


def test_orphan_notification_detected():
    notifications = (
        NotificationState(
            notification_id="notif-from-nonexistent-event",
            timestamp="t", message="m", severity="info",
        ),
    )
    state = WorldState(rooms=(_base_room(),), notifications=notifications)
    errors = validate(state)
    assert any("references missing event" in e for e in errors)


def test_notification_with_matching_event_is_not_orphan():
    events = (EventState(
        event_id="e1", timestamp="t", event_type="trade_fill",
        district="ceo-tower", severity="success",
    ),)
    notifications = (
        NotificationState(
            notification_id="notif-from-e1", timestamp="t", message="m", severity="success",
        ),
    )
    state = WorldState(rooms=(_base_room(),), events=events, notifications=notifications)
    assert validate(state) == []
