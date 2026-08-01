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
- `frontend/` — engine-agnostic renderer abstraction layer (Phase W3) plus
  concrete asset-pipeline code (Phase W6): `asset_loader/sources/` (four
  `AssetLoader` implementations), `asset_loader/registry_factory.py`,
  `asset_loader/compatibility.py`
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
- `docs/` — architecture, roadmap, coding/naming/asset conventions,
  ingestion adapter, state provider, office layout & room specs (W2), and
  asset pipeline & population reports (W6)
- `scripts/` — validation tooling (`validate_schemas.py`, a Phase W5
  runtime benchmark script, and Phase W6 asset validation)
- `tests/` — schema/uniqueness/relationship/adapter/cache/watcher/state/
  navigation/asset tests

## Status

Phase W6 — Renderer Integration + Asset Pipeline is in progress. The Asset
Pipeline half is complete: every department (plus lobby/hallway/elevator)
is populated with furniture and decoration metadata, every character has
sprite and spatial-placement metadata, and four concrete `AssetLoader`s
(OpenGameArt, LPC, Kenney, Custom) resolve against
`world/data/assets/asset_manifest.json` — see `world/docs/ASSET_PIPELINE.md`.
The Renderer Integration half is still outstanding: no renderer engine is
chosen, the Phase W3 `WorldStateProvider` ABC
(`world/frontend/interfaces/world_state.py`) is not yet implemented against
Phase W5's `WorldState`, and no binary sprites ship in this repo. Phase W4
(read-only ingestion adapter) and Phase W5 (World State Provider) are both
complete — the six Phase W4 runtime files plus static W1/W2 canon merge into
one immutable, in-memory `WorldState`, with caching, change detection,
validation, relationship resolution, and statistics. See
`docs/architecture/WORLD_OFFICE_POLICY.md` for the locked visual direction,
`world/docs/OFFICE_LAYOUT.md` for the floor plan,
`world/docs/INGESTION_ADAPTER.md` for the read-only data pipeline,
`world/docs/STATE_PROVIDER.md` for the state provider, and
`world/docs/ASSET_PIPELINE.md` for the asset pipeline.
