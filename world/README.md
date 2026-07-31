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
- `readers/`, `watchers/`, `adapter/`, `runtime/` — Phase W4 read-only
  ingestion pipeline; see `docs/INGESTION_ADAPTER.md`
- `docs/` — architecture, roadmap, coding/naming/asset conventions
- `scripts/` — placeholder validation tooling
- `tests/` — schema/uniqueness/relationship/adapter/cache/watcher tests

## Status

Phase W4 — Foundation materialized (W1A); office HQ theme locked and
retconned (W2); documentation synchronized (W2.1); renderer abstraction
layer built (W3); read-only ingestion adapter built (W4). No renderer
chosen yet, no sprites, no real engine `DataSource` wired. See
`docs/architecture/WORLD_OFFICE_POLICY.md` for the locked visual
direction, `world/docs/OFFICE_LAYOUT.md` for the floor plan, and
`world/docs/INGESTION_ADAPTER.md` for the read-only data pipeline.
