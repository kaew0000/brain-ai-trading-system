"""SceneGraphRenderer — Phase W8's concrete `Renderer`.

The concrete engine binding this phase picks — per
`world/docs/roadmap.md` item 10 ("pick a concrete renderer engine")
— is a **scene-graph compiler targeting Phaser 3**, not a Python
pixel-drawing library. Rationale, grounded in what's already in this
repository rather than invented for this phase:

- Every project doc/config that names concrete engines
  (`world/frontend/asset_loader/compatibility.py`'s `KNOWN_ENGINES`,
  every `world/data/assets/asset_manifest.json` entry's
  `compatibleWith` list) treats `"phaser"` as a first-class target
  alongside `react`/`pixijs`/`godot`/`unity` — `phaser` is not a name
  this phase introduces.
- `world/` is a pure-Python package with a hard rule (see
  `world/docs/coding-standards.md`) against depending on anything
  outside the plain-JSON-reading, engine-neutral contracts already
  established. Depending on `pygame`/`pixi`/`godot`-bridge/etc. from
  here would violate that rule for zero benefit, since the actual
  pixel target (per the project's stated stack: React + Vite +
  Phaser 3 + FastAPI + WebSocket) is a **browser**, not this Python
  process.
- The `Renderer`/`CharacterRenderer`/`DistrictRenderer` ABCs
  (`world/frontend/interfaces/`) are themselves void/side-effecting —
  written for direct engine calls. `SceneGraphRenderer` honors those
  signatures literally (accumulate, don't return) and exposes the
  accumulated result as a `render_state.RenderFrame` via
  `current_frame` — a plain, JSON-serializable scene graph a browser
  Phaser 3 scene (Phase W10) can consume over whatever transport that
  phase wires up. No transport code lives here.

Pipeline (matches the brief's diagram exactly):

    WorldState -> SceneBuilder -> Scene -> [character/room/overlay renderers] -> RenderFrame

`SceneCache` sits between `Scene`-building and command-emission,
keyed by `(room_id, world_state.sequence)`, so an unchanged tick for
a room already rendered is served from cache instead of rebuilt.

Never mutates `world_state` (it's a frozen dataclass; nothing here
would need to anyway) — matches the read-only presentation-layer
contract every interface docstring in this package repeats.
"""

from world.frontend.camera.camera import ReferenceCameraController
from world.frontend.interfaces.renderer import Renderer
from world.frontend.renderer.asset_locator import AssetLocator
from world.frontend.renderer.character_renderer import SpriteCharacterRenderer
from world.frontend.renderer.overlay_renderer import OverlayRenderer
from world.frontend.renderer.render_config import load_renderer_config
from world.frontend.renderer.render_state import RenderFrame
from world.frontend.renderer.room_renderer import OfficeDistrictRenderer, load_room_anchors
from world.frontend.renderer.scene_builder import build_scene
from world.frontend.renderer.scene_cache import SceneCache
from world.frontend.renderer.sprite_mapper import SpriteMapper
from world.frontend.renderer.world_state import WorldState
from world.frontend.rooms.room_type import all_room_type_ids
from world.frontend.scene.scene import Scene, SceneRegistry
from world.frontend.viewport.viewport import ViewportState


class RendererNotInitializedError(RuntimeError):
    """Raised by `load_scene`/`render`/`shutdown` if called before
    `initialize` — matches the `Renderer.initialize` ABC docstring's
    "Must not be called before initialize" requirement."""


class SceneGraphRenderer(Renderer):
    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = config_path
        self._initialized = False
        self._scene_registry = SceneRegistry()
        self._current_scene: Scene | None = None
        self._current_frame: RenderFrame | None = None
        self._scene_cache = SceneCache()
        self._asset_locator: AssetLocator | None = None
        self._sprite_mapper: SpriteMapper | None = None
        self._camera: ReferenceCameraController | None = None
        self._viewport: ViewportState | None = None
        self._room_anchors: dict[str, tuple[float, float]] = {}

    # -- Renderer ABC --------------------------------------------------

    def initialize(self) -> None:
        config = load_renderer_config(self._config_path) if self._config_path else load_renderer_config()
        self._room_anchors = load_room_anchors()
        self._camera = ReferenceCameraController(room_anchors=self._room_anchors)
        self._viewport = ViewportState(
            width=config.viewport_width,
            height=config.viewport_height,
            scale=config.viewport_scale,
        )
        self._asset_locator = AssetLocator()
        self._sprite_mapper = SpriteMapper()
        self._initialized = True

        if config.initial_scene_id:
            room_id = config.initial_scene_id
            scene = build_scene(scene_id=f"scene-{room_id}", room_id=room_id,
                                 world_state=WorldState(), asset_locator=self._asset_locator)
            self.load_scene(scene)

    def load_scene(self, scene: Scene) -> None:
        self._require_initialized()
        self._scene_registry.register(scene)
        self._current_scene = scene
        if scene.district_id in self._room_anchors:
            self._camera.focus_room(scene.district_id)

    def render(self, world_state: WorldState) -> None:
        self._require_initialized()
        if self._current_scene is None:
            raise RendererNotInitializedError("render() called with no scene loaded — call load_scene first")
        self._current_frame = self._scene_cache.get_or_build(
            room_id=self._current_scene.district_id,
            sequence=world_state.sequence,
            build=lambda: self._build_frame(self._current_scene, world_state),
        )

    def shutdown(self) -> None:
        self._require_initialized()
        self._scene_cache.invalidate()
        self._scene_registry = SceneRegistry()
        self._current_scene = None
        self._current_frame = None
        self._initialized = False

    # -- accessors -------------------------------------------------------

    @property
    def current_frame(self) -> RenderFrame | None:
        return self._current_frame

    @property
    def initialized(self) -> bool:
        return self._initialized

    def known_room_ids(self) -> list[str]:
        return all_room_type_ids()

    # -- internals -------------------------------------------------------

    def _require_initialized(self) -> None:
        if not self._initialized:
            raise RendererNotInitializedError(
                f"{type(self).__name__} used before initialize() was called"
            )

    def _build_frame(self, loaded_scene: Scene, world_state: WorldState) -> RenderFrame:
        # `load_scene` fixes *which room* is loaded; the room's actual
        # contents (which characters are in it, which events are
        # against it) change every simulation tick, so the `Scene` is
        # rebuilt fresh from the current `world_state` here rather
        # than reusing `loaded_scene`'s (load-time-stale) layers —
        # only `scene_id`/`district_id` (the stable "which scene"
        # identity) come from `loaded_scene`.
        scene = build_scene(
            scene_id=loaded_scene.scene_id, room_id=loaded_scene.district_id,
            world_state=world_state, asset_locator=self._asset_locator,
        )
        room_id = scene.district_id
        camera_state = self._camera.state
        room_data = dict(world_state.district_status.get(room_id, {}))

        district_renderer = OfficeDistrictRenderer(
            self._asset_locator, self._viewport, camera_state.x, camera_state.y,
            room_anchors=self._room_anchors,
        )
        district_renderer.render_district(room_id, room_data)

        origin_x, origin_y = self._room_anchors.get(room_id, (0.0, 0.0))
        character_renderer = SpriteCharacterRenderer(
            self._asset_locator, self._viewport, camera_state.x, camera_state.y,
            origin_x=origin_x, origin_y=origin_y,
        )
        overlay_renderer = OverlayRenderer()
        overlay_renderer.render_room_overlays(room_id, world_state)
        overlay_renderer.render_global_overlays(world_state)

        for character_id in scene.character_ids:
            position = world_state.character_positions.get(character_id)
            if position is None:
                continue
            behavior = world_state.character_states.get(character_id, "idle")
            animation_state = self._sprite_mapper.animation_state_for(behavior)
            character_renderer.render_character(character_id, position, animation_state)
            overlay_renderer.render_character_overlay(character_id, behavior)

        commands = (
            district_renderer.take_commands()
            + character_renderer.take_commands()
            + overlay_renderer.take_commands()
        )
        return RenderFrame(
            scene_id=scene.scene_id,
            room_id=room_id,
            sequence=world_state.sequence,
            camera={
                "x": camera_state.x, "y": camera_state.y,
                "zoom": camera_state.zoom, "focusMode": camera_state.focus_mode.value,
            },
            viewport={
                "width": self._viewport.width, "height": self._viewport.height,
                "scale": self._viewport.scale,
            },
            commands=tuple(commands),
        )
