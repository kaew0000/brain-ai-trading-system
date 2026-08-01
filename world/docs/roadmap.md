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
9. **W7** — Live Office Simulation: `world/simulation/` — `SimulationEngine`
   (Part A: clock, scheduler, movement, character behaviour, room
   activity, event descriptors, timeline, in one `step()`), 7 character
   behaviours and 6 room activity levels driven only by Phase W5's
   `WorldState` (Part B/C), abstract logical movement via Dijkstra over
   the real Phase W2 navigation graph (Part D), metadata-only event
   descriptors (Part E), a play/pause/resume/seek `Timeline` (Part F), the
   8-function `world.simulation.api` (Part G), and per-tick statistics
   (Part H). No renderer-specific code; no trading/execution/AI-decision
   logic invented. **Done** — this renumbers what earlier notes called
   "W7 Interaction Layer" to **W9** below, since Live Office Simulation
   needs only `WorldState` (W5) + asset metadata (W6), not the
   still-missing W6 renderer-integration half, and is itself a
   prerequisite for meaningful interaction (you need simulated behaviour
   states before wiring click/hover to them). See
   `world/docs/SIMULATION.md`.
10. **W8** — Renderer Integration (the part of the old W6 that never got
    done): pick a concrete renderer engine, implement the Phase W3
    `WorldStateProvider` ABC, static scene rendering. **Done.** Engine
    chosen: a backend scene-graph compiler targeting Phaser 3
    (`world.frontend.renderer.renderer.SceneGraphRenderer`) —
    `world/` stays a pure-Python, engine-neutral package per
    `docs/coding-standards.md`; the actual pixel target is the
    project's browser frontend (React + Vite + Phaser 3), wired up in
    W10. `world.frontend.renderer.world_state_provider.RenderWorldStateProvider`
    implements the Phase W3 `WorldStateProvider` ABC by projecting
    Phase W5's `WorldState` + Phase W7's `SimulationState` down to the
    Phase W3 renderer-facing shape. `world.frontend.renderer.scene_builder`
    builds a `Scene` per room from that projection;
    `character_renderer`/`room_renderer`/`overlay_renderer` emit a
    `render_state.RenderFrame` (a JSON-serializable scene graph) per
    render pass, cached per `(room_id, tick)` by `scene_cache.SceneCache`.
    Found and resolved two real data gaps rather than inventing
    around them (stale vs. active character-sprite-id sources; five
    sprite animation states vs. seven Phase W7 behaviour labels) — see
    `world/docs/RENDERER.md` for both. All 17 real rooms (14
    departments + 3 circulation types) render end to end against live
    Phase W5/W7 data. See `world/docs/RENDERER.md`.
11. **W9** — Interaction Layer: wire up the interaction metadata already
    defined (`world/data/interactions/`) plus Phase W7's `SimulationState`
    to real click/hover/walk-to behavior against the W8 renderer. Not
    started.
12. **W10** — Live Command Center: point real `DataSource` instances
    (Phase W4) at whatever the trading engine actually emits, schedule
    `RuntimeManager.run_once()` (a `Watcher`-gated loop or fixed interval),
    and implement the full UI panel set already specified in
    `world/ui/specs/` (minimap, inspectors, activity feed, notification
    center, relationship viewer, time control, simulation controls) against
    live data. Not started.
