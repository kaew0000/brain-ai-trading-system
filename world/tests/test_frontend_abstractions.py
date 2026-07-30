"""Phase W3: behavioral tests for every concrete (non-drawing) piece
of the renderer foundation, plus a check that every ABC interface
really is abstract (cannot be instantiated directly)."""

import inspect
import os

import pytest

from world.frontend.asset_loader.asset_registry import (
    AssetRegistry,
    AssetSource,
    UnresolvedAssetError,
)
from world.frontend.camera.camera import DEFAULT_ZOOM, FocusMode, ReferenceCameraController
from world.frontend.interfaces import (
    animation_controller,
    asset_loader,
    camera,
    character_renderer,
    district_renderer,
    layer,
    navigation_renderer,
    renderer,
    scene,
    sprite,
    tile,
    viewport,
    world_state,
)
from world.frontend.renderer.world_state import WorldState
from world.frontend.rooms.room_type import CirculationType, all_room_type_ids, load_department_ids
from world.frontend.scene.layer import STANDARD_LAYER_ORDER, Layer, LayerType
from world.frontend.scene.scene import Scene, SceneRegistry
from world.frontend.viewport.viewport import ViewportState, screen_to_world, world_to_screen

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

INTERFACE_MODULES = [
    (renderer, "Renderer"),
    (scene, "SceneRenderer"),
    (camera, "CameraController"),
    (viewport, "ViewportRenderer"),
    (asset_loader, "AssetLoader"),
    (sprite, "SpriteRenderer"),
    (tile, "TileRenderer"),
    (layer, "LayerRenderer"),
    (district_renderer, "DistrictRenderer"),
    (character_renderer, "CharacterRenderer"),
    (navigation_renderer, "NavigationRenderer"),
    (world_state, "WorldStateProvider"),
    (animation_controller, "AnimationController"),
]


@pytest.mark.parametrize("module,class_name", INTERFACE_MODULES, ids=[c for _, c in INTERFACE_MODULES])
def test_interface_is_abstract_and_cannot_be_instantiated(module, class_name):
    cls = getattr(module, class_name)
    assert inspect.isabstract(cls), f"{class_name} has no abstract methods — not a real interface"
    with pytest.raises(TypeError):
        cls()


def test_all_thirteen_interfaces_present():
    assert len(INTERFACE_MODULES) == 13


# ---------------------------------------------------------------- WorldState

def test_world_state_defaults_are_empty_and_frozen():
    state = WorldState()
    assert state.district_status == {}
    assert state.character_states == {}
    assert state.character_positions == {}
    assert state.recent_events == ()
    assert state.sequence == 0
    with pytest.raises(Exception):  # frozen dataclass -> FrozenInstanceError
        state.sequence = 1  # type: ignore[misc]


# ---------------------------------------------------------------- Layer

def test_standard_layer_order_has_all_seven_types():
    assert list(STANDARD_LAYER_ORDER) == list(LayerType)


def test_layer_dataclass_basic():
    layer_obj = Layer(layer_type=LayerType.CHARACTERS, z_order=3, entity_ids=["herald"])
    assert layer_obj.visible is True
    assert layer_obj.entity_ids == ["herald"]


# ---------------------------------------------------------------- Scene

def test_scene_registry_register_and_get():
    registry = SceneRegistry()
    scene_obj = Scene(scene_id="s1", district_id="world-gateway", character_ids=["herald"])
    registry.register(scene_obj)
    assert registry.get("s1") is scene_obj
    assert registry.get("missing") is None
    assert registry.all_scenes() == [scene_obj]


# ---------------------------------------------------------------- Camera

def test_reference_camera_controller_zoom_clamps():
    controller = ReferenceCameraController(room_anchors={"world-gateway": (2.0, 1.0)})
    assert controller.state.zoom == DEFAULT_ZOOM
    state = controller.zoom_to(999.0)
    assert state.zoom < 999.0  # clamped to MAX_ZOOM
    state = controller.zoom_to(-5.0)
    assert state.zoom > -5.0  # clamped to MIN_ZOOM


def test_reference_camera_controller_focus_room_unknown_raises():
    controller = ReferenceCameraController(room_anchors={"world-gateway": (2.0, 1.0)})
    with pytest.raises(KeyError):
        controller.focus_room("not-a-real-room")


def test_reference_camera_controller_focus_room_known():
    controller = ReferenceCameraController(room_anchors={"world-gateway": (2.0, 1.0)})
    state = controller.focus_room("world-gateway")
    assert (state.x, state.y) == (2.0, 1.0)
    assert state.focus_mode == FocusMode.ROOM
    assert state.focus_target == "world-gateway"


def test_reference_camera_controller_follow_character_tracks_updates():
    controller = ReferenceCameraController(room_anchors={})
    controller.update_character_position("herald", 1.0, 1.0)
    state = controller.follow_character("herald")
    assert (state.x, state.y) == (1.0, 1.0)
    controller.update_character_position("herald", 5.0, 5.0)
    assert (controller.state.x, controller.state.y) == (5.0, 5.0)


def test_reference_camera_controller_pan_clears_focus():
    controller = ReferenceCameraController(room_anchors={"world-gateway": (2.0, 1.0)})
    controller.focus_room("world-gateway")
    state = controller.pan_by(1.0, 0.0)
    assert state.focus_mode == FocusMode.FREE
    assert state.focus_target is None


# ---------------------------------------------------------------- Viewport

def test_world_to_screen_and_back_round_trips():
    vp = ViewportState(width=1280, height=720, scale=32.0)
    sx, sy = world_to_screen(vp, camera_x=0.0, camera_y=0.0, world_x=2.0, world_y=1.0)
    wx, wy = screen_to_world(vp, camera_x=0.0, camera_y=0.0, screen_x=sx, screen_y=sy)
    assert round(wx, 6) == 2.0
    assert round(wy, 6) == 1.0


# ---------------------------------------------------------------- AssetRegistry


class _AlwaysClaimsLoader:
    def can_load(self, asset_id):
        return asset_id.startswith("test-")

    def load(self, asset_id):
        return {"handle": asset_id}


def test_asset_registry_unresolved_raises():
    registry = AssetRegistry()
    with pytest.raises(UnresolvedAssetError):
        registry.resolve("nonexistent-asset")


def test_asset_registry_dispatches_to_registered_loader():
    registry = AssetRegistry()
    registry.register_loader(AssetSource.CUSTOM, _AlwaysClaimsLoader())
    handle = registry.resolve("test-asset-1")
    assert handle == {"handle": "test-asset-1"}
    assert AssetSource.CUSTOM in registry.registered_sources()


def test_asset_registry_caches_resolved_assets():
    registry = AssetRegistry()
    loader = _AlwaysClaimsLoader()
    registry.register_loader(AssetSource.CUSTOM, loader)
    first = registry.resolve("test-asset-1")
    second = registry.resolve("test-asset-1")
    assert first is second  # same cached object, loader not called twice
    registry.clear_cache()
    third = registry.resolve("test-asset-1")
    assert third == first  # equal value, cache was actually cleared and reloaded


# ---------------------------------------------------------------- RoomType

def test_load_department_ids_matches_real_district_count():
    ids = load_department_ids()
    assert len(ids) == 14
    assert "world-gateway" in ids
    assert "risk-fortress" in ids


def test_all_room_type_ids_includes_circulation_types():
    ids = all_room_type_ids()
    for circulation in CirculationType:
        assert circulation.value in ids
    assert len(ids) == 14 + len(list(CirculationType))


def test_circulation_type_elevator_matches_navigation_graph_node_type():
    """world/data/schemas/navigation.schema.json (Phase W2) already
    defines node "type" as one of room/elevator/hallway — confirms
    Phase W3's CirculationType didn't invent a second, inconsistent
    vocabulary."""
    import json

    schema_path = os.path.join(WORLD_ROOT, "data", "schemas", "navigation.schema.json")
    with open(schema_path) as f:
        schema = json.load(f)
    node_type_enum = schema["properties"]["nodes"]["items"]["properties"]["type"]["enum"]
    assert CirculationType.ELEVATOR.value in node_type_enum
    assert CirculationType.HALLWAY.value in node_type_enum
