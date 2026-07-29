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
5. **W3** — Design the read-only ingestion adapter (still no engine changes).
6. **W4** — Static scene rendering with placeholder shapes, pick a renderer.
7. **W5** — Asset pipeline activation (LPC sprites, tilesets, audio).
8. **W6** — Live data wiring (read-only) from real engine logs.
9. **W7** — Full UI panel implementation (minimap, inspectors, feeds).
