"""world.frontend.renderer.api — Phase W10, additive. The one public
surface most callers should use, completing the same convention
`world.runtime.api` (W5), `world.simulation.api` (W7), and
`world.interaction.api` (W9) already established: wrap one shared,
module-level instance so repeated calls share state, and expose plain
functions rather than requiring every caller to know `SceneGraphRenderer`'s
`initialize()`/`load_scene()`/`render()` lifecycle.

`world/frontend/renderer/` (Phase W8) was the one package of the four
without this facade — nothing needed it yet, the same reason
`world.simulation.api.get_timeline()` wasn't exposed until Phase W9 needed
it. Nothing in this module can mutate the trading engine, `world.runtime`,
or `world.simulation` — `get_render_frame` only ever calls
`get_current_state()` (Phase W3 ABC, read-only) and `SceneGraphRenderer.
render()` (which itself never mutates `world_state`, a frozen dataclass).
"""

from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.render_state import RenderFrame
from world.frontend.renderer.renderer import SceneGraphRenderer
from world.frontend.renderer.scene_builder import build_scene
from world.frontend.renderer.world_state_provider import RenderWorldStateProvider
from world.frontend.rooms.room_type import all_room_type_ids

_renderer = SceneGraphRenderer()
_provider = RenderWorldStateProvider()


def _ensure_initialized() -> None:
    if not _renderer.initialized:
        _renderer.initialize()


def get_render_frame(room_id: str) -> RenderFrame:
    """Return the current `RenderFrame` for `room_id`, initializing the
    renderer and/or switching the loaded scene only when needed."""
    _ensure_initialized()
    if _renderer.current_frame is None or _renderer.current_frame.room_id != room_id:
        world_state = _provider.get_current_state()
        scene = build_scene(
            scene_id=f"scene-{room_id}", room_id=room_id,
            world_state=world_state, asset_locator=AssetLocator(),
        )
        _renderer.load_scene(scene)
    world_state = _provider.get_current_state()
    _renderer.render(world_state)
    return _renderer.current_frame


def known_room_ids() -> list[str]:
    return all_room_type_ids()


__all__ = ["get_render_frame", "known_room_ids"]
