# world/frontend — Renderer Foundation (Phase W3) + Renderer (Phase W8)

Phase W3 (`interfaces/`, `scene/`, `camera/`, `viewport/`, `rooms/`,
the base `asset_loader/`) is the engine-agnostic abstraction layer;
Phase W8 (`renderer/`, beyond the Phase W3 `WorldState` shape it
already held) is the concrete engine binding chosen against it — see
`docs/RENDERER.md`. The engine picked is a backend scene-graph
compiler targeting Phaser 3, not a Python pixel-drawing library —
this package stays engine-neutral; the actual pixel target is the
project's browser frontend, wired up in Phase W10.

## Layout

```
world/frontend/
  interfaces/       13 ABCs — the behavior contracts (no drawing code)
  renderer/          Phase W3: WorldState (the snapshot shape a Renderer
                      consumes). Phase W8: SceneGraphRenderer (concrete
                      Renderer), RenderWorldStateProvider (concrete
                      WorldStateProvider), scene_builder, sprite_mapper,
                      asset_locator, character_renderer, room_renderer,
                      overlay_renderer, scene_cache, render_state,
                      render_config — see docs/RENDERER.md
  scene/              Scene, Layer/LayerType — static per-room content
  camera/             CameraState + ReferenceCameraController (state-only)
  viewport/           ViewportState + world<->screen coordinate math
  asset_loader/       AssetRegistry, AssetSource, Sprite, Tile, plus
                      concrete AssetLoaders + registry_factory (Phase W6)
  rooms/              RoomType taxonomy (derived from real district data)
  schemas/            JSON Schemas for renderer/camera/layer/asset configs
```

## Two kinds of module in this package

**`interfaces/`** — pure `abc.ABC` contracts. Four now have a concrete
Phase W8 implementation: `Renderer` (`renderer.SceneGraphRenderer`),
`CharacterRenderer` (`character_renderer.SpriteCharacterRenderer`),
`DistrictRenderer` (`room_renderer.OfficeDistrictRenderer`), and
`WorldStateProvider` (`world_state_provider.RenderWorldStateProvider`).
`CameraController` has had a concrete (state-only) implementation
since Phase W3 (`ReferenceCameraController`, below). The rest remain
interface-only and undeferred by design, not oversight —
`SceneRenderer`, `LayerRenderer`, `SpriteRenderer`, `TileRenderer` are
subsumed by `SceneGraphRenderer`'s single `render_state.RenderCommand`
output for a data-compiling (not per-primitive-drawing) renderer;
`NavigationRenderer` (minimap) has no consumer until an interaction
layer needs one; `AnimationController` still has no implementation
since no binary sprite-sheet asset exists in this repo to drive frame
stepping against. See `docs/RENDERER.md`'s "What is not implemented
this phase" section.

**Everything else** (`renderer/`, `scene/`, `camera/`, `viewport/`,
`asset_loader/`, `rooms/`) — concrete, engine-agnostic **state and
data**, not rendering. `ReferenceCameraController` is the one
exception worth calling out: it's a full implementation of the
`CameraController` interface, but it only computes *where the camera
should be* (a `CameraState`) — it never draws a pixel. This was worth
building now because the zoom/pan/focus-room/focus-character/
follow-character/center-room math is renderer-independent, and every
future concrete renderer needs the same answer to "where is the
camera."

## What's still deferred (as of Phase W8)

- No binary sprite/tile/audio *files* ship in this repo — every asset
  reference resolves to `asset_manifest.json` metadata (source, tags,
  version, engine compatibility), not pixels. A real Phaser 3 scene
  reading that metadata to actually fetch and draw assets is Phase
  W10's job.
- No animation implementation — `AnimationController` is interface
  only; still nothing to drive frame stepping against (see above).
- No transport — `render_state.RenderFrame.to_dict()` is
  JSON-serializable but nothing in this package sends it anywhere
  (FastAPI/WebSocket wiring is Phase W10).
- No interaction wiring — click/hover/walk-to against the renderer is
  Phase W9.

Resolved this phase (previously listed here as deferred): a concrete
engine is chosen; `AssetRegistry` has all four loaders registered by
default (`asset_locator.AssetLocator`, via
`asset_loader.registry_factory.build_default_registry`); `WorldStateProvider`
has a concrete, live-data implementation
(`world_state_provider.RenderWorldStateProvider`).
