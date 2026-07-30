# world/frontend — Renderer Foundation (Phase W3)

No renderer is chosen yet. This package is the abstraction layer every
future concrete renderer (a PixiJS/Phaser/Godot/Unity/React Canvas
binding — any of them) will implement against, so that choice can be
made later (Phase W5) without touching this package's contracts.

## Layout

```
world/frontend/
  interfaces/       12 ABCs — the behavior contracts (no drawing code)
  renderer/          WorldState — the snapshot shape a Renderer consumes
  scene/              Scene, Layer/LayerType — static per-room content
  camera/             CameraState + ReferenceCameraController (state-only)
  viewport/           ViewportState + world<->screen coordinate math
  asset_loader/       AssetRegistry, AssetSource, Sprite, Tile
  rooms/              RoomType taxonomy (derived from real district data)
  schemas/            JSON Schemas for renderer/camera/layer/asset configs
```

## Two kinds of module in this package

**`interfaces/`** — pure `abc.ABC` contracts. Zero implementation.
These are what a concrete renderer engine implements: `Renderer`,
`SceneRenderer`, `CameraController`, `ViewportRenderer`, `AssetLoader`,
`SpriteRenderer`, `TileRenderer`, `LayerRenderer`, `DistrictRenderer`,
`CharacterRenderer`, `NavigationRenderer`, `WorldStateProvider`, and
`AnimationController` (interface only, per an explicit requirement —
no animation implementation exists anywhere in this repo yet).

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

## What's explicitly deferred

- No engine chosen (Phase W5, per `world/docs/roadmap.md`).
- No sprites/tiles/audio — `AssetRegistry` has zero loaders registered;
  `AssetLoader` implementations for OpenGameArt/LPC/Kenney/custom
  don't exist yet (Phase W6, asset pipeline activation).
- No live data — `WorldStateProvider` has no implementation;
  `WorldState` always starts empty (Phase W4 designs the read-only
  ingestion adapter that would populate it; Phase W7 wires it live).
- No animation implementation — `AnimationController` is interface
  only, by explicit requirement.
