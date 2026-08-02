"""Phase W9: SelectionManager."""

import pytest

from world.interaction.selection_manager import SelectionManager, UnknownSelectionTargetError
from world.runtime.models import AgentState, RoomState, WorldState
from world.simulation.models import EventDescriptor


def _fake_world_state():
    return WorldState(
        rooms=(RoomState(room_id="risk-fortress", name="Risk Department", is_active=True),),
        agents=(AgentState(agent_id="bastion", agent_ref="BASTION", current_room_id="risk-fortress"),),
    )


def _fake_events():
    return (EventDescriptor(event_id="evt-1", kind="risk_alert", room_id="risk-fortress"),)


def _manager(tmp_path, rows=None):
    room_assets_path = tmp_path / "room_assets.json"
    room_assets_path.write_text(_room_assets_json(rows if rows is not None else _default_rows()))
    return SelectionManager(
        room_assets_path=str(room_assets_path),
        get_world_state=_fake_world_state,
        get_current_events=_fake_events,
    )


def _default_rows():
    return [{
        "roomId": "risk-fortress",
        "furniturePlacements": [{"instanceId": "risk-fortress.furniture.desk.0", "furnitureId": "furniture.desk"}],
        "decorationPlacements": [{"instanceId": "risk-fortress.decoration.plant.0", "decorationId": "decoration.plant"}],
    }]


def _room_assets_json(rows):
    import json
    return json.dumps(rows)


def test_select_room_that_exists(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("room", "risk-fortress")
    assert selection.kind == "room"
    assert selection.target_id == "risk-fortress"
    assert manager.current == selection


def test_select_department_resolves_against_same_room_ids(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("department", "risk-fortress")
    assert selection.kind == "department"


def test_select_unknown_room_raises(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(UnknownSelectionTargetError):
        manager.select("room", "nonexistent-room")


def test_select_character_that_exists(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("character", "bastion")
    assert selection.kind == "character"


def test_select_unknown_character_raises(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(UnknownSelectionTargetError):
        manager.select("character", "nonexistent-agent")


def test_select_furniture_instance(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("furniture", "risk-fortress.furniture.desk.0")
    assert selection.kind == "furniture"


def test_select_decoration_instance(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("decoration", "risk-fortress.decoration.plant.0")
    assert selection.kind == "decoration"


def test_select_unknown_furniture_raises(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(UnknownSelectionTargetError):
        manager.select("furniture", "nonexistent.furniture.0")


def test_select_current_event(tmp_path):
    manager = _manager(tmp_path)
    selection = manager.select("event", "evt-1")
    assert selection.kind == "event"


def test_select_unknown_event_raises(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(UnknownSelectionTargetError):
        manager.select("event", "nonexistent-evt")


def test_select_invalid_kind_raises_value_error(tmp_path):
    manager = _manager(tmp_path)
    with pytest.raises(ValueError):
        manager.select("spaceship", "anything")


def test_clear_resets_current_selection(tmp_path):
    manager = _manager(tmp_path)
    manager.select("room", "risk-fortress")
    manager.clear()
    assert manager.current is None


def test_no_selection_by_default(tmp_path):
    manager = _manager(tmp_path)
    assert manager.current is None
