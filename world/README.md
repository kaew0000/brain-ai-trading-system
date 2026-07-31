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
- `districts/definitions/` — one JSON file per district
- `ui/specs/` — design specs for planned UI panels (design only, not implemented)
- `minimap/` — minimap schema (design only)
- `scenes/` — scene manifest schema (design only)
- `data/schemas/` — stable JSON Schemas for all world data contracts
- `data/samples/` — example payloads validating each schema
- `data/runtime/` — Phase W4 live snapshot output (`world.json`,
  `events.json`, `missions.json`, `portfolio.json`, `telemetry.json`,
  `notifications.json`) — written only by `RuntimeManager`
- `frontend/` — Phase W3 engine-agnostic renderer abstraction layer
  (interfaces + concrete state, no renderer chosen)
- `readers/`, `watchers/`, `adapter/` — Phase W4 read-only ingestion
  pipeline; see `docs/INGESTION_ADAPTER.md`
- `runtime/` — Phase W4 `runtime_manager.py` + `cache.py` (writes
  `data/runtime/*.json`) plus Phase W5 `models.py`, `state_builder.py`,
  `state_cache.py`, `update_manager.py`, `relationship_resolver.py`,
  `state_validator.py`, `statistics.py`, `world_state_provider.py`, `api.py`
  (reads `data/runtime/*.json`, produces an in-memory `WorldState`) —
  see `docs/STATE_PROVIDER.md`
- `docs/` — architecture, roadmap, coding/naming/asset conventions,
  ingestion adapter and state provider design docs
- `scripts/` — validation tooling (`validate_schemas.py`; a Phase W5
  runtime benchmark script)
- `tests/` — schema/uniqueness/relationship/adapter/cache/watcher/state
  tests

## Status

Phase W5 — World State Provider complete: the six Phase W4 runtime files
plus static W1/W2 canon now merge into one immutable, in-memory
`WorldState`, with caching, change detection, validation, relationship
resolution, and statistics. Still no renderer chosen, no sprites, no real
engine `DataSource` wired — that's Phase W6 (Renderer Integration), which
also folds in the Phase W6 Asset Pipeline work built earlier but never
merged. See `docs/architecture/WORLD_OFFICE_POLICY.md` for the locked
visual direction, `world/docs/OFFICE_LAYOUT.md` for the floor plan,
`world/docs/INGESTION_ADAPTER.md` for the read-only data pipeline, and
`world/docs/STATE_PROVIDER.md` for the state provider.
