# Renderer Integration (Phase W8)

Implements the two things `world/docs/roadmap.md` flagged as
outstanding since the old "Phase W6" was split into W6 (asset
pipeline)/W7 (simulation)/W8 (this phase): **pick a concrete renderer
engine**, and **implement the Phase W3 `WorldStateProvider` ABC**.
Lives entirely under `world/frontend/renderer/`, `world/frontend/schemas/`,
and `world/frontend/samples/` — no other `world/` package changed, and
nothing outside `world/` was touched.

## Engine choice: a Phaser 3 scene-graph compiler, not a Python renderer

`world/` is a pure-Python, engine-neutral package by design (see
`world/docs/coding-standards.md`); the project's actual pixel target
is a browser (React + Vite + Phaser 3, per the project's stated
stack). So "pick a concrete renderer engine" here means: pick what
shape of data this backend hands to that browser frontend, not pick a
Python graphics library. `world.frontend.renderer.renderer.SceneGraphRenderer`
is a `Renderer` (`world/frontend/interfaces/renderer.py`)
implementation that computes a complete, backend-independent scene
graph — a `render_state.RenderFrame` — every render pass, and never
imports pygame/pixi/godot-bridge/anything pixel-specific. The engine
identifier registered for this (`"phaser"`, in
`render_config.ENGINE_ID` and `renderer_config.schema.json`'s
`engine` enum) reuses the vocabulary
`world.frontend.asset_loader.compatibility.KNOWN_ENGINES` and every
`asset_manifest.json` entry's `compatibleWith` list already used —
not a name this phase invented.

Wiring an actual Phaser 3 scene to consume `RenderFrame.to_dict()`
over a transport (the existing FastAPI/WebSocket layer is the natural
fit) is Phase W10 (Live Command Center) — no transport code lives
here.

## Pipeline

```
world.runtime.api.get_world_state()        (Phase W5: room/agent identity)
world.simulation.api.get_simulation_state() (Phase W7: per-tick behaviour/position/activity)
                    |
                    v
    world_state_provider.RenderWorldStateProvider   <- implements the Phase W3 WorldStateProvider ABC
                    |
                    v
       world.frontend.renderer.world_state.WorldState   (flattened, Phase W3 shape)
                    |
                    v
            scene_builder.build_scene(room_id, world_state, asset_locator)
                    |
                    v
       world.frontend.scene.scene.Scene  (7 layers, STANDARD_LAYER_ORDER)
                    |
                    v
   renderer.SceneGraphRenderer._build_frame  -- drives, per room:
     room_renderer.OfficeDistrictRenderer   (floor + furniture + decoration commands)
     character_renderer.SpriteCharacterRenderer (one sprite command per character)
     overlay_renderer.OverlayRenderer        (labels, status, meeting/emergency flags, clock)
                    |
                    v
            render_state.RenderFrame   (JSON-serializable; .to_dict())
```

`scene_cache.SceneCache` sits between `Scene`-building and
command-emission inside `SceneGraphRenderer.render()`, keyed by
`(room_id, world_state.sequence)` — a repeated `render()` call for a
tick already built is served from cache, not rebuilt.

## Why `Renderer`/`CharacterRenderer`/`DistrictRenderer` return `None`

Those three Phase W3 ABCs are void, side-effecting draw calls, written
for a direct engine binding (call once per frame/character/room, it
draws immediately). This phase's concrete implementations honor that
literally: each accumulates `render_state.RenderCommand`s into an
internal buffer instead of drawing one, and exposes
`take_commands()`/`current_frame` to retrieve what was accumulated.
This is the one place this phase's design diverges from "a real
engine binding would draw here" — documented rather than silently
reinterpreted, since a future *actual* pixel-drawing `Renderer`
(a different concrete class, still satisfying the same ABC) would
draw instead of buffer, and nothing above `world/frontend/interfaces/`
needs to change either way.

## Two real gaps found and resolved (not invented)

**1. Character sprite ids: two disagreeing sources.**
`world/characters/definitions/<id>.json`'s `spriteMeta.animations`
(Phase W1/W2, e.g. `"bastion_idle"`) never matches any
`world/data/assets/asset_manifest.json` id. `world/data/assets/character_assets.json`'s
`spriteAssetIds` (Phase W6, e.g. `"sprite.bastion.idle"`) matches for
all 16 characters × 5 states — verified this phase. `sprite_mapper.SpriteMapper`
uses the latter exclusively; see its module docstring for the full
comparison.

**2. Seven behaviours, five sprites.**
`world.simulation.models.CHARACTER_BEHAVIORS` (Phase W7) has seven
labels (`idle`, `walking`, `working`, `meeting`, `emergency`,
`celebration`, `resting`); every character's real sprite set only has
five (`idle`, `walking`, `working`, `celebration`, `emergency` — the
same five as the Phase W3 `AnimationController.STANDARD_ANIMATION_STATES`).
No `meeting`/`resting` sprite exists for any character. Rather than
invent asset ids that don't resolve, `render_config.BEHAVIOR_TO_ANIMATION_STATE`
documents an explicit fallback (`meeting -> working`,
`resting -> idle`) in one place. `world.frontend.renderer.world_state.WorldState.character_states`
still stores the *raw* seven-label behaviour, unmapped — the fallback
is applied one layer down, only at sprite-selection time, so no
information is silently dropped from `WorldState` itself. Adding real
`meeting`/`resting` sprites later is an asset-pipeline task; this
map should shrink to the identity mapping once that ships, with no
other code changes needed.

## Coordinate system (a verified finding, not an assumption)

`world/data/layout/rooms.json`'s `cameraAnchor`/`spawnLocation` are
**floor-scale** office-unit coordinates (e.g. `ai-council`:
`{"x": 2.0, "y": 16.0}`). Furniture/decoration positions
(`world/data/assets/room_assets.json`) and character positions
(`world.simulation.api.get_simulation_state()`) are **room-local**
(e.g. every position for `bastion` in `risk-fortress` falls in the
0–4 range matching `world/data/characters/placement.json`'s
`deskAnchor`). No document states how the two combine; this phase
makes the simplest reading explicit: `world_position = room_anchor +
local_position`, one abstract office unit the same size in both
systems. `room_renderer.py`'s module docstring carries the full
finding; only `room_renderer.room_origin`/`character_renderer`'s
`origin_x`/`origin_y` encode the assumption, so a future correction
is a one-place change.

Only the 14 departments have a `rooms.json` `cameraAnchor` entry — the
three `CirculationType` rooms (`lobby`, `hallway`, `elevator`) fall
back to origin `(0, 0)`. This is a real data gap (documented in
`room_renderer.py`), not a bug: those three rooms still render (floor,
furniture, decorations, occupancy status all resolve — verified for
all 17 rooms by `world/tests/test_renderer_integration.py`'s
regression sweep), just without a real position on the office floor
plan until `world/data/layout/rooms.json` gets anchors for them.

## Scene graph / frame lifecycle

1. `SceneGraphRenderer.initialize()` — loads `renderer_config.sample.json`
   (or a caller-supplied path), builds the `ViewportState`, a
   `ReferenceCameraController` seeded with every department's
   `cameraAnchor` (`room_renderer.load_room_anchors()`), an
   `AssetLocator`, a `SpriteMapper`, and loads the configured
   `initialScene` (`world-gateway` by default).
2. `load_scene(scene)` — registers a `Scene` and focuses the camera on
   its room (if that room has a `cameraAnchor`). Fixes *which room* is
   loaded; does not fix its contents.
3. `render(world_state)` — rebuilds the `Scene` fresh from the current
   `world_state` (occupancy/behaviour/events change every tick even
   though the loaded room doesn't), served through `SceneCache`, then
   drives the three sub-renderers and assembles a `RenderFrame`.
   Never mutates `world_state` (it's a frozen dataclass; nothing here
   would need to anyway).
4. `shutdown()` — clears the cache and scene registry, resets to
   uninitialized.

## What is *not* implemented this phase

Documented explicitly rather than left to be discovered: only 4 of
the 13 Phase W3 interfaces get a concrete implementation this phase
(`Renderer`, `CharacterRenderer`, `DistrictRenderer`,
`WorldStateProvider`). `SceneRenderer`, `LayerRenderer`,
`SpriteRenderer`, `TileRenderer`, `NavigationRenderer`, and
`AnimationController` remain interface-only — `RenderCommand` already
covers what `LayerRenderer`/`SpriteRenderer`/`TileRenderer` would
each draw one piece of, for a data-compiling (not per-primitive
drawing) renderer, and `NavigationRenderer` (minimap) / `AnimationController`
(real sprite-sheet frame stepping) have no consumer yet — both are
natural Phase W9/W10 work, not invented here.

"Clock"/simulation-speed overlays (`overlay_renderer.OverlayRenderer.render_global_overlays`)
carry only the Phase W7 tick number, since that's what the Phase W3
`WorldState` shape `Renderer.render(world_state)` receives — richer
`simulated_seconds`/running-paused state would mean extending that
already-shipped dataclass, out of scope here. See `overlay_renderer.py`'s
module docstring.

## Backend abstraction / future renderer adapters

Nothing under `world/frontend/interfaces/`, `world/frontend/scene/`,
`world/frontend/camera/`, or `world/frontend/viewport/` changed this
phase, and nothing in this phase's new code is Phaser-specific beyond
the `engine` config string and this doc's naming — `render_state.RenderCommand`/`RenderFrame`
are plain dicts-of-primitives a PixiJS, Godot, or Unity consumer could
equally read. A future alternate `Renderer` implementation (e.g. one
that draws directly via a Python-side engine instead of compiling a
scene graph) only needs to satisfy the same `Renderer`/`CharacterRenderer`/
`DistrictRenderer` ABCs — `scene_builder.build_scene`, `AssetLocator`,
and `SpriteMapper` are all engine-agnostic and reusable as-is.

## Testing

`world/tests/test_renderer_*.py` (8 files, ~80 tests): unit coverage
for `sprite_mapper`, `asset_locator`, `world_state_provider`,
`scene_cache`, `scene_builder`, `character_renderer`/`room_renderer`
(including a regression pin for the room-origin coordinate bug this
phase found and fixed during self-testing), `overlay_renderer`, and a
`test_renderer_integration.py` end-to-end suite that renders all 17
real rooms against live `world.runtime`/`world.simulation` data and
asserts every resulting frame is JSON-serializable. Run:

```
pytest world/tests -m ""   # pytest.ini's default -m "unit" filter
                            # doesn't apply to world/tests
```
