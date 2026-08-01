# Architecture Overview

See the root [WORLD.md](../WORLD.md) for the full Phase W1 report. This file
mirrors the key points for readers browsing `docs/` directly.

Brain AI Command World is a one-directional, read-only reflection of engine
state:

```
Trading Engine -> DataSource -> Reader -> Adapter -> world/data/runtime/*.json -> StateBuilder -> WorldState -> renderer -> UI panels
```

(See the fully current version of this diagram, with `SimulationEngine`
and the Phase W8 renderer stages included, near the end of this file.)

No arrow points back into the engine. See `naming-conventions.md`,
`coding-standards.md`, and `asset-conventions.md` for how contributions to
this folder should be structured.

**Visual theme (Phase W2):** Brain AI Command World is a modern office
headquarters, not a fantasy setting — this is locked, see
`docs/architecture/WORLD_OFFICE_POLICY.md` and `WORLD_DESIGN_LOCK.md`
(canonical) and `OFFICE_LAYOUT.md` in this folder for the current floor
plan and department list.

**Ingestion (Phase W4):** the middle three arrows above
(`DataSource -> Reader -> Adapter`) are implemented at `world/readers/`,
`world/adapter/`, and `world/runtime/runtime_manager.py` — see
`INGESTION_ADAPTER.md` and `RUNTIME_DATA_FLOW.md` in this folder. No
`DataSource` points at a real engine file yet; `world/data/runtime/*.json`
are honest idle placeholders.

**World State Provider (Phase W5):** `StateBuilder -> WorldState` above is
implemented at `world/runtime/{models,state_builder,state_cache,
update_manager,relationship_resolver,state_validator,statistics,
world_state_provider,api}.py` — see `STATE_PROVIDER.md` in this folder.
Pure backend, in-memory only; no renderer chosen or touched.

**Asset pipeline (Phase W6, done):** every department, plus lobby/hallway/
elevator, is populated with furniture and decoration metadata; every
character has sprite and spatial-placement metadata. Four concrete
`AssetLoader`s (OpenGameArt, LPC, Kenney, Custom) resolve against
`world/data/assets/asset_manifest.json` — see `ASSET_PIPELINE.md` in this
folder.

**Live Office Simulation (Phase W7, done):** a new stage now sits between
`WorldState` and any future renderer: `SimulationEngine.step()`
(`world/simulation/`) derives 7 character behaviours + 6 room activity
levels + metadata-only event descriptors from `WorldState` and the Phase
W6 spatial-placement data, tracked through a play/pause/resume/seek
`Timeline`. No renderer-specific code. Updated diagram:

```
Trading Engine -> DataSource -> Reader -> Adapter -> world/data/runtime/*.json
    -> StateBuilder -> WorldState -> SimulationEngine -> SimulationState
    -> renderer (any engine, W8+) -> UI panels
```

See `SIMULATION.md` in this folder.

**Renderer integration (Phase W8, done):** the final leg of the diagram
above, `SimulationState -> renderer`, is now built —
`world/frontend/renderer/`. Concrete engine chosen: a backend
scene-graph compiler targeting Phaser 3 (`SceneGraphRenderer`), not a
Python pixel-drawing library — `world/` stays engine-neutral per this
file's own rule; the actual pixel target is the project's browser
frontend (React + Vite + Phaser 3), wired up in Phase W10.
`RenderWorldStateProvider` implements the Phase W3 `WorldStateProvider`
ABC by projecting `WorldState` + `SimulationState` down to the
flattened Phase W3 shape; `scene_builder`/`character_renderer`/
`room_renderer`/`overlay_renderer` turn that into a JSON-serializable
`RenderFrame` per room per tick. Still no binary asset files ship in
this repo — every asset reference resolves to
`asset_manifest.json` metadata, not pixels; a real Phaser 3 scene
consuming this data is Phase W10's job. (This stage was called "Phase
W6, outstanding" in earlier notes; renumbered to W8 per
`world/docs/roadmap.md` once Phase W7 was built ahead of it.) See
`RENDERER.md` in this folder. Final diagram:

```
Trading Engine -> DataSource -> Reader -> Adapter -> world/data/runtime/*.json
    -> StateBuilder -> WorldState -> SimulationEngine -> SimulationState
    -> RenderWorldStateProvider -> SceneGraphRenderer -> RenderFrame
    -> Phaser 3 frontend (W10) -> UI panels
```
