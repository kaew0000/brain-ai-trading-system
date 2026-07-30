# Development Roadmap

1. **W1** — Architecture, schemas, lore skeleton, docs (documentation only). **Done.**
2. **W1A** — Materialize folder structure and placeholder files in-repo. **Done.**
3. **W2** — Office Headquarters Foundation: retcon fantasy theme to modern
   office HQ per `docs/architecture/WORLD_OFFICE_POLICY.md` /
   `WORLD_DESIGN_LOCK.md`; add `world/data/layout`, `world/data/characters`
   (placement), `world/data/navigation` as a spatial layer on top of the
   existing W1 district/character data. **Done.**
4. **W2.1** — Office Documentation Synchronization: bring `WORLD.md`, this
   roadmap, `world/lore/`, `world/ui/specs/`, and `world/docs/architecture.md`
   into agreement with the Phase W2 office theme. No data, schema, engine, or
   layout changes. **Done.**
5. **W3** — Renderer Foundation: engine-agnostic abstraction layer
   (`world/frontend/` — 13 interfaces, concrete state-only Scene/Camera/
   Viewport/AssetRegistry/RoomType, no renderer chosen, no sprites, no live
   data). **Done.**
6. **W4** — Read-only ingestion adapter: `world/readers/` (5 generic,
   source-agnostic readers behind a `DataSource`/`Reader` split),
   `world/watchers/` (2 change-detection strategies), `world/adapter/`
   (orchestration + `EngineSnapshot` + `SnapshotBuilder`),
   `world/runtime/runtime_manager.py` (+ hash-based `SnapshotCache`,
   writes only to `world/data/runtime/`). No `DataSource` points at a
   real engine path yet — see `world/docs/INGESTION_ADAPTER.md`. **Done.**
7. **W5** — World State Provider: pure backend, in-memory world state.
   `world/runtime/models.py` (frozen dataclasses: `WorldState`, `RoomState`,
   `AgentState`, `MissionState`, `PortfolioState`, `NotificationState`,
   `EventState`, `TelemetryState`), `state_builder.py` (merges all six
   Phase W4 runtime files with static W1/W2 canon), `state_cache.py` +
   `update_manager.py` (TTL + hash-based change detection, no polling
   loop), `relationship_resolver.py`, `state_validator.py`,
   `statistics.py`, `world_state_provider.py`, and `api.py` (the 5 public
   read-only functions). Explicitly does **not** implement the Phase W3
   `WorldStateProvider` ABC or choose a renderer — see
   `world/docs/STATE_PROVIDER.md` §9. **Done.**
8. **W6** — Renderer Integration + Asset Pipeline: (a) pick a concrete
   renderer engine and implement the Phase W3 interfaces against it; (b)
   implement the Phase W3 `WorldStateProvider` ABC by projecting Phase
   W5's `WorldState` down to the renderer-facing shape; (c) static scene
   rendering with placeholder shapes; (d) asset pipeline — concrete
   `AssetLoader` for all four `AssetSource` values (OpenGameArt, LPC,
   Kenney, Custom), asset manifest, asset packs, compatibility layer, and
   full office population (furniture + decorations in every room,
   character asset + spatial placement for every character). **Asset
   pipeline (d) done** — see `world/docs/ASSET_PIPELINE.md`. **Renderer
   integration (a)–(c) not started.**
9. **W7** — Interaction Layer: wire up the interaction metadata already
   defined (`world/data/interactions/`) to real click/hover/walk-to
   behavior against the chosen W6 renderer. Not started.
10. **W8** — Live Command Center: point real `DataSource` instances
    (Phase W4) at whatever the trading engine actually emits, schedule
    `RuntimeManager.run_once()` (a `Watcher`-gated loop or fixed interval),
    and implement the full UI panel set already specified in
    `world/ui/specs/` (minimap, inspectors, activity feed, notification
    center, relationship viewer, time control, simulation controls) against
    live data. Not started.
