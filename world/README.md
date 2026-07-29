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
- `docs/` — architecture, roadmap, coding/naming/asset conventions
- `scripts/` — placeholder validation tooling
- `tests/` — placeholder schema/uniqueness/relationship tests

## Status

Phase W2.1 — Foundation materialized (W1A); office HQ theme locked and
retconned (W2); documentation synchronized (W2.1). No renderer chosen yet,
no sprites. See `docs/architecture/WORLD_OFFICE_POLICY.md` for the locked
visual direction and `world/docs/OFFICE_LAYOUT.md` for the current floor
plan.
