# Architecture Overview

See the root [WORLD.md](../WORLD.md) for the full Phase W1 report. This file
mirrors the key points for readers browsing `docs/` directly.

Brain AI Command World is a one-directional, read-only reflection of engine
state:

```
Trading Engine -> DataSource -> Reader -> Adapter -> world/data/runtime/*.json -> renderer (any engine) -> UI panels
```

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
`world/adapter/`, and `world/runtime/` — see `INGESTION_ADAPTER.md` and
`RUNTIME_DATA_FLOW.md` in this folder. No `DataSource` points at a real
engine file yet; `world/data/runtime/*.json` are honest idle placeholders.
