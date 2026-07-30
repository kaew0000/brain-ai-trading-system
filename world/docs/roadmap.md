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
6. **W4** — Design the read-only ingestion adapter (still no engine
   changes) — implements `world.frontend.interfaces.world_state.WorldStateProvider`.
7. **W5** — Static scene rendering with placeholder shapes; pick a concrete
   renderer engine and implement the Phase W3 interfaces against it.
8. **W6** — Asset pipeline activation (office-appropriate sprites, tilesets,
   audio) — implement `AssetLoader` for at least one `AssetSource`.
9. **W7** — Live data wiring (read-only) from real engine logs.
10. **W8** — Full UI panel implementation (the 8 panels already specified in
    `world/ui/specs/`, now backed by a real renderer).
