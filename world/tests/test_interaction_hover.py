"""Phase W9: HoverManager."""

from world.interaction.hover_manager import HoverManager
from world.runtime.models import RoomState
from world.simulation.models import (
    CharacterActivity,
    EventDescriptor,
    Position,
    RoomActivityState,
    SimulationState,
    SimulationTick,
)


def _fake_simulation_state():
    return SimulationState(
        tick=SimulationTick(tick_number=5, simulated_seconds=5.0, world_sequence=5),
        characters=(
            CharacterActivity(agent_id="bastion", agent_ref="BASTION", behavior="working",
                               room_id="risk-fortress", position=Position(0.5, 0.5)),
        ),
        rooms=(RoomActivityState(room_id="risk-fortress", activity="busy", occupant_count=1),),
        events=(EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="risk-fortress",
                                 agent_id="bastion", message="risk flagged"),),
    )


def _fake_get_room_state(room_id):
    if room_id == "risk-fortress":
        return RoomState(room_id="risk-fortress", name="Risk Department")
    return None


def _manager():
    return HoverManager(get_simulation_state=_fake_simulation_state, get_room_state=_fake_get_room_state)


def test_hover_character_returns_behavior_and_room_name():
    info = _manager().hover("character", "bastion")
    assert info.status == "working"
    assert info.room_info == "Risk Department"
    assert info.current_event == "risk flagged"
    assert info.simulation_clock["tickNumber"] == 5


def test_hover_unknown_character_returns_empty_shape():
    info = _manager().hover("character", "nobody")
    assert info.status == ""
    assert info.simulation_clock["tickNumber"] == 5


def test_hover_room_returns_activity_and_name():
    info = _manager().hover("room", "risk-fortress")
    assert info.activity == "busy"
    assert info.room_info == "Risk Department"
    assert info.current_event == "risk flagged"


def test_hover_department_kind_behaves_like_room():
    info = _manager().hover("department", "risk-fortress")
    assert info.activity == "busy"


def test_hover_furniture_returns_clock_only():
    info = _manager().hover("furniture", "risk-fortress.furniture.desk.0")
    assert info.status == ""
    assert info.activity == ""
    assert info.simulation_clock["tickNumber"] == 5
