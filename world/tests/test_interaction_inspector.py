"""Phase W9: build_inspector_report."""

from world.interaction.inspector import build_inspector_report
from world.runtime.models import AgentState, RoomState, WorldState
from world.simulation.models import (
    CharacterActivity,
    Position,
    RoomActivityState,
    SimulationState,
    SimulationTick,
)
from world.simulation.timeline import Timeline


def _fake_world_state():
    return WorldState(
        rooms=(RoomState(room_id="risk-fortress", name="Risk Department", is_active=True,
                          occupant_agent_ids=("bastion",), active_mission_ids=("m1",)),),
        agents=(AgentState(agent_id="bastion", agent_ref="BASTION", current_room_id="risk-fortress",
                            is_active=True, status="working"),),
    )


def _sim_state(tick_number, behavior="working", activity="busy"):
    return SimulationState(
        tick=SimulationTick(tick_number=tick_number, simulated_seconds=float(tick_number), world_sequence=tick_number),
        characters=(CharacterActivity(agent_id="bastion", agent_ref="BASTION", behavior=behavior,
                                       room_id="risk-fortress", position=Position(0.5, 0.5)),),
        rooms=(RoomActivityState(room_id="risk-fortress", activity=activity, occupant_count=1),),
    )


def _fake_get_simulation_state():
    return _sim_state(3, behavior="meeting", activity="meeting")


def _fake_timeline_with_history():
    timeline = Timeline()
    timeline.record(_sim_state(1, behavior="idle", activity="quiet"))
    timeline.record(_sim_state(2, behavior="working", activity="busy"))
    timeline.record(_sim_state(3, behavior="meeting", activity="meeting"))
    return timeline


def test_character_report_merges_runtime_and_simulation():
    report = build_inspector_report(
        "character", "bastion",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert report.id == "bastion"
    assert report.name == "BASTION"
    assert report.current_state == "working"  # runtime AgentState.status
    assert report.simulation_status == "meeting"  # current tick's simulation behavior
    assert report.location == "Risk Department"
    assert report.assigned_agent == "BASTION"
    assert report.linked_runtime_data["isActive"] is True


def test_character_report_historical_timeline_has_every_recorded_tick():
    report = build_inspector_report(
        "character", "bastion",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert [h.tick_number for h in report.historical_timeline] == [1, 2, 3]
    assert [h.behavior_or_activity for h in report.historical_timeline] == ["idle", "working", "meeting"]


def test_room_report_merges_runtime_and_simulation():
    report = build_inspector_report(
        "room", "risk-fortress",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert report.name == "Risk Department"
    assert report.current_state == "active"
    assert report.simulation_status == "meeting"
    assert report.linked_runtime_data["activeMissionIds"] == ["m1"]
    assert report.linked_runtime_data["occupantCount"] == 1


def test_department_kind_behaves_like_room():
    report = build_inspector_report(
        "department", "risk-fortress",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert report.kind == "room"


def test_furniture_report_is_identity_only():
    report = build_inspector_report(
        "furniture", "risk-fortress.furniture.desk.0",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert report.id == "risk-fortress.furniture.desk.0"
    assert report.kind == "furniture"
    assert report.historical_timeline == ()


def test_unknown_character_id_still_returns_a_report():
    report = build_inspector_report(
        "character", "nobody",
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert report.name == "nobody"
    assert report.current_state == ""
    assert report.historical_timeline == ()


def test_history_limit_truncates_to_most_recent():
    report = build_inspector_report(
        "character", "bastion", history_limit=2,
        get_world_state=_fake_world_state, get_simulation_state=_fake_get_simulation_state,
        get_timeline=_fake_timeline_with_history,
    )
    assert [h.tick_number for h in report.historical_timeline] == [2, 3]
