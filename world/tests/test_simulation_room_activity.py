"""Phase W7, Part C: room activity — precedence order exercised in
isolation, matching `room_activity.determine_room_activity`'s own
documented order."""
from world.runtime.models import EventState, MissionState, RoomState, WorldState
from world.simulation.room_activity import determine_room_activity


def test_quiet_when_empty_and_nothing_happening():
    room = RoomState(room_id="ceo-tower", name="CEO Office")
    state = WorldState(rooms=(room,))
    assert determine_room_activity(room, state) == "quiet"


def test_busy_when_occupied():
    room = RoomState(room_id="ceo-tower", name="CEO Office", occupant_agent_ids=("primus",))
    state = WorldState(rooms=(room,))
    assert determine_room_activity(room, state) == "busy"


def test_critical_overrides_everything():
    room = RoomState(room_id="ceo-tower", name="CEO Office", occupant_agent_ids=("primus",))
    events = (EventState(event_id="e1", timestamp="t", event_type="risk_alert",
                          district="ceo-tower", severity="critical"),)
    state = WorldState(rooms=(room,), events=events)
    assert determine_room_activity(room, state) == "critical"


def test_alert_on_warning_severity():
    room = RoomState(room_id="ceo-tower", name="CEO Office")
    events = (EventState(event_id="e1", timestamp="t", event_type="drawdown_warning",
                          district="ceo-tower", severity="warning"),)
    state = WorldState(rooms=(room,), events=events)
    assert determine_room_activity(room, state) == "alert"


def test_meeting_when_two_occupants_and_active_mission():
    room = RoomState(room_id="ai-council", name="AI Department",
                      occupant_agent_ids=("primus", "oracle"), active_mission_ids=("m1",))
    missions = (MissionState(mission_id="m1", title="X", district="ai-council", status="active"),)
    state = WorldState(rooms=(room,), missions=missions)
    assert determine_room_activity(room, state) == "meeting"


def test_meeting_takes_precedence_over_busy():
    room = RoomState(room_id="ai-council", name="AI Department",
                      occupant_agent_ids=("primus", "oracle"), active_mission_ids=("m1",))
    missions = (MissionState(mission_id="m1", title="X", district="ai-council", status="active"),)
    state = WorldState(rooms=(room,), missions=missions)
    assert determine_room_activity(room, state) == "meeting"


def test_celebration_on_growth_event():
    room = RoomState(room_id="portfolio-garden", name="Garden")
    events = (EventState(event_id="e1", timestamp="t", event_type="portfolio_growth",
                          district="portfolio-garden", severity="success"),)
    state = WorldState(rooms=(room,), events=events)
    assert determine_room_activity(room, state) == "celebration"


def test_alert_takes_precedence_over_meeting():
    room = RoomState(room_id="ai-council", name="AI Department",
                      occupant_agent_ids=("primus", "oracle"), active_mission_ids=("m1",))
    missions = (MissionState(mission_id="m1", title="X", district="ai-council", status="active"),)
    events = (EventState(event_id="e1", timestamp="t", event_type="drawdown_warning",
                          district="ai-council", severity="warning"),)
    state = WorldState(rooms=(room,), missions=missions, events=events)
    assert determine_room_activity(room, state) == "alert"
