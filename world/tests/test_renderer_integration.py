"""Phase W8: SceneGraphRenderer — end-to-end pipeline integration and a
full regression sweep across every real room, using the live Phase
W5/W7 data (same read path `world_state_provider.RenderWorldStateProvider`
uses in production)."""

import inspect
import json

import pytest

from world.frontend.interfaces.renderer import Renderer
from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.render_config import ENGINE_ID, load_renderer_config
from world.frontend.renderer.render_state import RenderFrame
from world.frontend.renderer.renderer import RendererNotInitializedError, SceneGraphRenderer
from world.frontend.renderer.scene_builder import build_scene
from world.frontend.renderer.world_state_provider import RenderWorldStateProvider
from world.frontend.rooms.room_type import all_room_type_ids


def _fresh_renderer() -> SceneGraphRenderer:
    r = SceneGraphRenderer()
    r.initialize()
    return r


def test_scene_graph_renderer_is_a_real_renderer():
    assert inspect.isabstract(Renderer)
    r = SceneGraphRenderer()
    assert isinstance(r, Renderer)


def test_render_before_initialize_raises():
    r = SceneGraphRenderer()
    with pytest.raises(RendererNotInitializedError):
        r.render(RenderWorldStateProvider().get_current_state())


def test_load_scene_before_initialize_raises():
    r = SceneGraphRenderer()
    world_state = RenderWorldStateProvider().get_current_state()
    scene = build_scene("s1", "risk-fortress", world_state, AssetLocator())
    with pytest.raises(RendererNotInitializedError):
        r.load_scene(scene)


def test_initialize_loads_the_configured_initial_scene():
    r = _fresh_renderer()
    config = load_renderer_config()
    assert r.initialized
    world_state = RenderWorldStateProvider().get_current_state()
    r.render(world_state)
    assert r.current_frame.room_id == config.initial_scene_id
    r.shutdown()


def test_render_with_no_scene_loaded_raises():
    """Defensive guard for a state `initialize()`'s default config
    path never actually produces (it always loads
    `config.initial_scene_id`), but that `load_scene` is itself
    optional per the `Renderer` ABC — a caller could construct a
    renderer, call `initialize()`, and never call `load_scene()`."""
    r = SceneGraphRenderer()
    r.initialize()
    r._current_scene = None
    with pytest.raises(RendererNotInitializedError):
        r.render(RenderWorldStateProvider().get_current_state())
    r.shutdown()


def test_render_produces_a_render_frame():
    r = _fresh_renderer()
    world_state = RenderWorldStateProvider().get_current_state()
    r.load_scene(build_scene("s-risk", "risk-fortress", world_state, AssetLocator()))
    r.render(world_state)
    frame = r.current_frame
    assert isinstance(frame, RenderFrame)
    assert frame.room_id == "risk-fortress"
    assert frame.sequence == world_state.sequence
    assert len(frame.commands) > 0
    r.shutdown()


def test_render_frame_is_json_serializable():
    r = _fresh_renderer()
    world_state = RenderWorldStateProvider().get_current_state()
    r.load_scene(build_scene("s-risk", "risk-fortress", world_state, AssetLocator()))
    r.render(world_state)
    payload = json.dumps(r.current_frame.to_dict())
    assert len(payload) > 0
    r.shutdown()


def test_repeated_render_same_sequence_is_served_from_cache():
    r = _fresh_renderer()
    world_state = RenderWorldStateProvider().get_current_state()
    r.load_scene(build_scene("s-risk", "risk-fortress", world_state, AssetLocator()))
    r.render(world_state)
    r.render(world_state)  # same sequence -> cache hit, not a rebuild
    assert r._scene_cache.hits == 1
    assert r._scene_cache.misses == 1
    r.shutdown()


def test_shutdown_resets_renderer_state():
    r = _fresh_renderer()
    world_state = RenderWorldStateProvider().get_current_state()
    r.load_scene(build_scene("s-risk", "risk-fortress", world_state, AssetLocator()))
    r.render(world_state)
    r.shutdown()
    assert r.initialized is False
    assert r.current_frame is None
    with pytest.raises(RendererNotInitializedError):
        r.render(world_state)


def test_render_never_mutates_world_state():
    r = _fresh_renderer()
    world_state = RenderWorldStateProvider().get_current_state()
    before = world_state.to_dict() if hasattr(world_state, "to_dict") else dict(world_state.__dict__)
    r.load_scene(build_scene("s-risk", "risk-fortress", world_state, AssetLocator()))
    r.render(world_state)
    after = world_state.to_dict() if hasattr(world_state, "to_dict") else dict(world_state.__dict__)
    assert before == after
    r.shutdown()


def test_engine_id_is_a_known_compatibility_engine():
    from world.frontend.asset_loader.compatibility import KNOWN_ENGINES
    assert ENGINE_ID in KNOWN_ENGINES


@pytest.mark.parametrize("room_id", all_room_type_ids())
def test_every_real_room_renders_without_error(room_id):
    """Full regression sweep: every one of the 17 real rooms (14
    departments + 3 circulation types) must build a scene and render a
    frame against live Phase W5/W7 data without raising, and every
    frame must be JSON-serializable."""

    r = SceneGraphRenderer()
    r.initialize()
    world_state = RenderWorldStateProvider().get_current_state()
    r.load_scene(build_scene(f"s-{room_id}", room_id, world_state, AssetLocator()))
    r.render(world_state)
    frame = r.current_frame
    assert frame.room_id == room_id
    json.dumps(frame.to_dict())  # raises if not serializable
    r.shutdown()
