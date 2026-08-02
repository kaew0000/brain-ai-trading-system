# Brain AI Command World

A read-only visualization, storytelling, and simulation layer for Brain Bot V16.

This folder is completely independent from the trading engine. Nothing here
executes trades, manages risk, or modifies engine behavior. It only reflects
state that the engine already produces.

See [WORLD.md](WORLD.md) for the full architecture, and [docs/](docs/) for
deeper documentation (architecture, roadmap, conventions).

## Folder Map

- `lore/` — narrative lore for the office, departments, and characters
- `assets/` — reserved for future sprites/tilesets/audio (empty in Phase W1)
- `characters/definitions/` — one JSON file per character (presentation only)
- `districts/definitions/` — one JSON file per district (office departments, Phase W2)
- `ui/specs/` — design specs for planned UI panels (design only, not implemented)
- `minimap/` — minimap schema (design only)
- `scenes/` — scene manifest schema (design only)
- `frontend/` — engine-agnostic renderer abstraction layer (Phase W3);
  concrete asset-pipeline code (Phase W6): `asset_loader/sources/` (four
  `AssetLoader` implementations), `asset_loader/registry_factory.py`,
  `asset_loader/compatibility.py`; concrete renderer (Phase W8):
  `renderer/` — `SceneGraphRenderer`, `RenderWorldStateProvider`,
  `scene_builder`, `sprite_mapper`, `asset_locator`, `character_renderer`,
  `room_renderer`, `overlay_renderer`, `scene_cache`, `render_state`,
  `render_config` — see `docs/RENDERER.md`
- `data/schemas/` — stable JSON Schemas for all world data contracts
- `data/samples/` — example payloads validating each schema
- `data/runtime/` — Phase W4 live snapshot output (`world.json`,
  `events.json`, `missions.json`, `portfolio.json`, `telemetry.json`,
  `notifications.json`) — written only by `RuntimeManager`
- `readers/`, `watchers/`, `adapter/` — Phase W4 read-only ingestion
  pipeline; see `docs/INGESTION_ADAPTER.md`
- `runtime/` — Phase W4 `runtime_manager.py` + `cache.py` (writes
  `data/runtime/*.json`) plus Phase W5 `models.py`, `state_builder.py`,
  `state_cache.py`, `update_manager.py`, `relationship_resolver.py`,
  `state_validator.py`, `statistics.py`, `world_state_provider.py`, `api.py`
  (reads `data/runtime/*.json`, produces an in-memory `WorldState`) —
  see `docs/STATE_PROVIDER.md`
- `data/layout/`, `data/characters/`, `data/navigation/` — office spatial
  layer (Phase W2) plus `data/characters/spatial_placement.json` (Phase W6,
  additive)
- `data/assets/` — asset manifest, packs, furniture/decoration catalogs,
  room population, character asset refs (Phase W6)
- `data/interactions/` — interaction type catalog (Phase W6)
- `simulation/` — `SimulationEngine`, character behaviour, room activity,
  movement (Dijkstra over the real nav graph), event descriptors,
  `Timeline`, statistics, and the 8-function `api.py` (Phase W7) — see
  `docs/SIMULATION.md`
- `interaction/` — `SelectionManager`, `HoverManager`, `build_inspector_report`,
  `FocusManager` (camera wrapper), `TimelineController` (seek/replay),
  `NotificationCenter`, `search`, `filters`, `CommandDispatcher`,
  `EventBus`, `InteractionHistory`, and the public `api.py` (Phase W9,
  read-only over Phase W5+W7+W8 state) — see `docs/INTERACTION_LAYER.md`
- `docs/` — architecture, roadmap, coding/naming/asset conventions,
  ingestion adapter, state provider, office layout & room specs (W2),
  asset pipeline & population reports (W6), the simulation layer (W7),
  the renderer (W8), and the interaction layer (W9)
- `scripts/` — validation tooling (`validate_schemas.py`, Phase W5/W7
  performance benchmarks, Phase W6 asset validation)
- `tests/` — schema/uniqueness/relationship/adapter/cache/watcher/state/
  navigation/asset/simulation/renderer/interaction tests

## Status

Phase W9 — Interactive Command Center is done: `world/interaction/`
adds selection, hover, an Inspector Panel (merging Phase W5 identity +
Phase W7 behaviour/activity + retained `Timeline` history), a
`FocusManager` wrapping Phase W8's `ReferenceCameraController`
(Focus Room / Follow Character / Center Camera), timeline seek/replay/
jump-to-event, a Notification Center built only from
`SimulationState` per design, search, filters, a read-only
`CommandDispatcher` (no trading commands), a six-event `EventBus`
(SelectionChanged, HoverChanged, CameraMoved, TimelineChanged,
SimulationPaused, SimulationResumed), and bounded interaction history.
See `world/docs/INTERACTION_LAYER.md`.

Phase W8 — Renderer Integration is done: `world/frontend/renderer/`
picks a concrete engine (a backend scene-graph compiler targeting
Phaser 3, not a Python pixel-drawing library — `world/` stays
engine-neutral; the actual pixel target is the project's browser
frontend, wired up in Phase W10) and implements the Phase W3
`WorldStateProvider` ABC by projecting Phase W5's `WorldState` +
Phase W7's `SimulationState` down to the flattened Phase W3 shape.
Every render pass produces a JSON-serializable `RenderFrame` for one
room, cached per `(room_id, tick)`. All 17 rooms (14 departments + 3
circulation types) render against live data. See
`world/docs/RENDERER.md`.

Phase W7 — Live Office Simulation is done: `world/simulation/` derives 7
character behaviours and 6 room activity levels purely from Phase W5's
`WorldState`, with abstract logical movement (Dijkstra over the real Phase
W2 navigation graph), metadata-only event descriptors, and a play/pause/
resume/seek `Timeline` — see `world/docs/SIMULATION.md`. No trading/
AI-decision logic invented.

Phase W6's Asset Pipeline half is complete: every
department (plus lobby/hallway/elevator) is populated with furniture and
decoration metadata, every character has sprite and spatial-placement
metadata, and four concrete `AssetLoader`s (OpenGameArt, LPC, Kenney,
Custom) resolve against `world/data/assets/asset_manifest.json`. Phase W4
(read-only ingestion adapter) and Phase W5 (World State Provider) are both
complete. See `docs/architecture/WORLD_OFFICE_POLICY.md` for the locked
visual direction, `world/docs/OFFICE_LAYOUT.md` for the floor plan,
`world/docs/INGESTION_ADAPTER.md` for the read-only data pipeline,
`world/docs/STATE_PROVIDER.md` for the state provider,
`world/docs/ASSET_PIPELINE.md` for the asset pipeline,
`world/docs/SIMULATION.md` for the simulation layer,
`world/docs/RENDERER.md` for the renderer, and
`world/docs/INTERACTION_LAYER.md` for the interaction layer.

Next: **Phase W10** — Live Command Center UI (the `world/ui/specs/` panel
set as an actual browser frontend, consuming Phase W8's `RenderFrame` and
Phase W9's `world.interaction.api`).
