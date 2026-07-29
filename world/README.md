# Brain AI Command World

A read-only visualization, storytelling, and simulation layer for Brain Bot V16.

This folder is completely independent from the trading engine. Nothing here
executes trades, manages risk, or modifies engine behavior. It only reflects
state that the engine already produces.

See [WORLD.md](WORLD.md) for the full architecture, and [docs/](docs/) for
deeper documentation (architecture, roadmap, conventions).

## Folder Map

- `lore/` — narrative lore for the city, districts, and characters
- `assets/` — reserved for future sprites/tilesets/audio (empty in Phase W1)
- `characters/definitions/` — one JSON file per character (presentation only)
- `districts/definitions/` — one JSON file per district
- `ui/specs/` — design specs for planned UI panels (design only, not implemented)
- `minimap/` — minimap schema (design only)
- `scenes/` — scene manifest schema (design only)
- `data/schemas/` — stable JSON Schemas for all world data contracts
- `data/samples/` — example payloads validating each schema
- `docs/` — architecture, roadmap, coding/naming/asset conventions
- `scripts/` — placeholder validation tooling
- `tests/` — placeholder schema/uniqueness/relationship tests

## Status

Phase W1A — Foundation materialized. No renderer chosen yet, no sprites, no maps.
