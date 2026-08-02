"""Phase W8: SceneBuilder — WorldState -> Scene for one room."""

from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.scene_builder import build_scene
from world.frontend.renderer.world_state import WorldState
from world.frontend.scene.layer import STANDARD_LAYER_ORDER


def _world_state():
    return WorldState(
        district_status={"risk-fortress": {"name": "Risk Department", "activity": "meeting"}},
        character_states={"bastion": "meeting", "sentinel": "idle", "chronos": "idle"},
        character_positions={
            "bastion": {"room_id": "risk-fortress", "x": 0.5, "y": 0.5},
            "sentinel": {"room_id": "risk-fortress", "x": 1.5, "y": 0.5},
            "chronos": {"room_id": "ceo-tower", "x": 0.2, "y": 0.2},
        },
        recent_events=(
            {"eventId": "evt-1", "roomId": "risk-fortress", "kind": "risk_alert"},
            {"eventId": "evt-2", "roomId": "ceo-tower", "kind": "trade_opened"},
        ),
        sequence=7,
    )


def test_scene_layers_follow_standard_layer_order():
    locator = AssetLocator()
    scene = build_scene("scene-1", "risk-fortress", _world_state(), locator)
    assert [layer.layer_type for layer in scene.layers] == list(STANDARD_LAYER_ORDER)


def test_scene_only_includes_characters_in_that_room():
    locator = AssetLocator()
    scene = build_scene("scene-1", "risk-fortress", _world_state(), locator)
    assert set(scene.character_ids) == {"bastion", "sentinel"}
    assert "chronos" not in scene.character_ids


def test_furniture_layer_includes_room_props():
    locator = AssetLocator()
    scene = build_scene("scene-1", "risk-fortress", _world_state(), locator)
    furniture_layer = scene.layers[2]
    assert furniture_layer.layer_type.value == "furniture"
    assert len(furniture_layer.entity_ids) == len(locator.room_props("risk-fortress"))


def test_effects_layer_only_includes_emergency_or_celebration_characters():
    locator = AssetLocator()
    scene = build_scene("scene-1", "risk-fortress", _world_state(), locator)
    effects_layer = scene.layers[4]
    assert effects_layer.entity_ids == []  # meeting/idle are not effect behaviors


def test_notification_layer_only_includes_events_for_that_room():
    locator = AssetLocator()
    scene = build_scene("scene-1", "risk-fortress", _world_state(), locator)
    notification_layer = scene.layers[6]
    assert notification_layer.entity_ids == ["evt-1"]


def test_scene_for_room_with_no_characters_or_events_is_still_valid():
    locator = AssetLocator()
    scene = build_scene("scene-1", "lobby", WorldState(), locator)
    assert scene.character_ids == []
    assert [layer.layer_type for layer in scene.layers] == list(STANDARD_LAYER_ORDER)
