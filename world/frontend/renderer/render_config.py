"""Renderer configuration — Phase W8.

Loads `world/frontend/samples/renderer_config.sample.json` (validated
against `world/frontend/schemas/renderer_config.schema.json` by
`world/tests/test_frontend_schemas.py`) and exposes the constants a
concrete renderer needs, so nothing in `world/frontend/renderer/`
hardcodes a viewport size, engine name, or initial scene — per
`world/docs/coding-standards.md` and the project-wide "never hardcode
values" rule.

This module also holds `BEHAVIOR_TO_ANIMATION_STATE`, the one
documented gap this phase found and had to resolve rather than
invent silently: `world.simulation.models.CHARACTER_BEHAVIORS` (Phase
W7) has seven labels (`idle`, `walking`, `working`, `meeting`,
`emergency`, `celebration`, `resting`), but every character's actual
sprite set in `world/data/assets/character_assets.json` (Phase W6)
only ships five animations (`idle`, `walking`, `working`,
`celebration`, `emergency` — the same five as the Phase W3
`AnimationController.STANDARD_ANIMATION_STATES`). No asset exists for
`meeting` or `resting` for any of the 16 characters. Rather than
fabricate sprite ids that don't exist in
`world/data/assets/asset_manifest.json`, this phase maps the two
unmatched behaviours onto the closest existing animation and records
that decision here, in one place, so it's visible and overridable
instead of buried in renderer logic:

- `meeting` -> `working` (character is stationary and engaged; no
  dedicated "in a meeting" sprite exists yet)
- `resting` -> `idle` (recovery-center rest state; no dedicated
  "resting" sprite exists yet)

Adding real `meeting`/`resting` sprites later (new
`world/data/assets/asset_manifest.json` entries plus matching
`spriteAssetIds` in `character_assets.json` for all 16 characters) is
an asset-pipeline task, not a renderer one — once that ships, this
map should shrink back to the identity mapping and nothing in
`world/frontend/renderer/` needs to change.
"""

import json
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/renderer
_FRONTEND_DIR = os.path.dirname(_THIS_DIR)  # world/frontend
_DEFAULT_CONFIG_PATH = os.path.join(_FRONTEND_DIR, "samples", "renderer_config.sample.json")

#: The renderer engine identifier this phase registers. Must be a
#: member of `world.frontend.asset_loader.compatibility.KNOWN_ENGINES`
#: — reusing that existing vocabulary rather than inventing a second
#: name for the same target, and must match
#: `renderer_config.schema.json`'s `engine` enum (updated this phase
#: to allow `"phaser"` alongside the Phase W3 placeholder `"none"`).
ENGINE_ID = "phaser"

#: Fallback default viewport, used only if no config file/override is
#: supplied. Real callers should load `renderer_config.sample.json`
#: (or their own config of the same shape) via `load_renderer_config`.
DEFAULT_VIEWPORT_WIDTH = 1280
DEFAULT_VIEWPORT_HEIGHT = 720
DEFAULT_VIEWPORT_SCALE = 32.0
DEFAULT_INITIAL_SCENE_ID = "world-gateway"

#: See module docstring. `world.simulation.models.CHARACTER_BEHAVIORS`
#: is the input domain; every value here must be one of the five keys
#: actually present in every `character_assets.json` `spriteAssetIds`
#: block (asserted by `world/tests/test_renderer_sprite_mapper.py`).
BEHAVIOR_TO_ANIMATION_STATE = {
    "idle": "idle",
    "walking": "walking",
    "working": "working",
    "celebration": "celebration",
    "emergency": "emergency",
    "meeting": "working",
    "resting": "idle",
}

#: Scene rebuild is skipped (served from `SceneCache`) whenever the
#: room's occupants, behaviours, and activity level are unchanged
#: between two `WorldState` snapshots. This bounds how many distinct
#: (room_id, cache-key) entries `SceneCache` keeps before evicting the
#: least-recently-used entry.
SCENE_CACHE_MAX_ENTRIES = 64


class RendererConfig:
    """Plain value object mirroring `renderer_config.schema.json`."""

    def __init__(self, engine: str, viewport_width: int, viewport_height: int,
                 viewport_scale: float, initial_scene_id: str | None) -> None:
        self.engine = engine
        self.viewport_width = viewport_width
        self.viewport_height = viewport_height
        self.viewport_scale = viewport_scale
        self.initial_scene_id = initial_scene_id


def load_renderer_config(path: str = _DEFAULT_CONFIG_PATH) -> RendererConfig:
    """Read a renderer config JSON file (default: the checked-in
    `renderer_config.sample.json`) and return a `RendererConfig`.
    Falls back to the module-level `DEFAULT_*` constants for any
    optional field the file omits, and to the full default set if the
    file itself is missing — so importing/using this module never
    fails outside a full repo checkout, matching the pattern already
    used by `world.frontend.asset_loader.sources.base.load_manifest`
    and `world.frontend.rooms.room_type.load_department_ids`."""
    if not os.path.isfile(path):
        return RendererConfig(
            engine=ENGINE_ID,
            viewport_width=DEFAULT_VIEWPORT_WIDTH,
            viewport_height=DEFAULT_VIEWPORT_HEIGHT,
            viewport_scale=DEFAULT_VIEWPORT_SCALE,
            initial_scene_id=DEFAULT_INITIAL_SCENE_ID,
        )
    with open(path) as f:
        raw = json.load(f)
    viewport = raw.get("viewport", {})
    return RendererConfig(
        engine=raw.get("engine", ENGINE_ID),
        viewport_width=viewport.get("width", DEFAULT_VIEWPORT_WIDTH),
        viewport_height=viewport.get("height", DEFAULT_VIEWPORT_HEIGHT),
        viewport_scale=viewport.get("scale", DEFAULT_VIEWPORT_SCALE),
        initial_scene_id=raw.get("initialSceneId", DEFAULT_INITIAL_SCENE_ID),
    )
