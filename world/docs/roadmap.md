# Development Roadmap

1. **W1** — Architecture, schemas, lore skeleton, docs (documentation only).
2. **W1A** — Materialize folder structure and placeholder files in-repo.
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
   `world/runtime/` (`RuntimeManager` + hash-based `SnapshotCache`,
   writes only to `world/data/runtime/`). No `DataSource` points at a
   real engine path yet — see `world/docs/INGESTION_ADAPTER.md`.
   **Done.** Does *not* yet implement
   `world.frontend.interfaces.world_state.WorldStateProvider` (Phase
   W3) — that binding is proposed as the first W5 task, see below.
7. **W5** — Renderer Integration: (a) implement `WorldStateProvider`
   by reading `world/data/runtime/*.json` and constructing a
   `WorldState`; (b) pick a concrete renderer engine and implement the
   Phase W3 interfaces against it; (c) static scene rendering with
   placeholder shapes. Not started.
8. **W6** — Asset pipeline activation (office-appropriate sprites, tilesets,
   audio) — implement `AssetLoader` for at least one `AssetSource`.
9. **W7** — Live data wiring: point real `DataSource` instances (Phase W4)
   at whatever the trading engine actually emits, and schedule
   `RuntimeManager.run_once()` (a `Watcher`-gated loop or fixed interval —
   design deferred to this phase).
10. **W8** — Full UI panel implementation (the 8 panels already specified in
    `world/ui/specs/`, now backed by a real renderer).
