# Architecture Overview

See the root [WORLD.md](../WORLD.md) for the full Phase W1 report. This file
mirrors the key points for readers browsing `docs/` directly.

Brain AI Command World is a one-directional, read-only reflection of engine
state:

```
Trading Engine -> DataSource -> Reader -> Adapter -> world/data/runtime/*.json -> StateBuilder -> WorldState -> renderer (any engine, W6+) -> UI panels
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

**Renderer integration (Phase W6, outstanding):** the final leg of the
diagram above, `WorldState -> renderer`, is not yet built — the Phase W3
`WorldStateProvider` ABC still needs to be implemented against Phase W5's
`WorldState`, no renderer engine is chosen, and no binary asset files ship
in this repo.
