# Development Roadmap

> **Pre-W1 note (added 2026-08-02, Repository Stabilization phase):**
> `feat(world): performance v1` (commit `9ad1ab5`, merged via PR #5,
> 2026-07-20) predates W1 (first commit `d74ba2c`, 2026-07-29) by ten
> days and is not part of this numbered sequence — historical
> background only, not renumbered as "W0". See `world/WORLD.md`'s
> matching note and `docs/REPOSITORY_STABILIZATION_REPORT.md` for
> detail.

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
11. **W9** — Interactive Command Center: `world/interaction/` —
    `SelectionManager` (validates room/department/character/furniture/
    decoration/event ids against real Phase W5/W6/W7 data before
    accepting a selection), `HoverManager` (lightweight per-tick status/
    activity/room/clock/event), `build_inspector_report` (merges Phase
    W5 identity + Phase W7 behaviour/activity + retained `Timeline`
    history + `relationship_resolver` department ownership),
    `FocusManager` (wraps Phase W8's `ReferenceCameraController` for
    Focus Room / Follow Character / Center Camera), `TimelineController`
    (seek/replay/pause/resume/jump-to-event, via one additive function —
    `world.simulation.api.get_timeline()` — added to expose Phase W7's
    already-built `Timeline`), `NotificationCenter` (built only from
    `SimulationState` per this phase's brief, not Phase W5's own
    `NotificationState`; category mapping documented in-module as a
    judgment call, not fabricated data), `search` and `filters`
    (department / room type / agent state / simulation state / alerts /
    meetings), a read-only `CommandDispatcher` (9 commands; no trading
    commands; `set_simulation_speed` is stored as a UI preference with
    no backend effect, documented as such, since Phase W7 has no
    tick-cadence concept to control), a six-event `EventBus`
    (SelectionChanged, HoverChanged, CameraMoved, TimelineChanged,
    SimulationPaused, SimulationResumed), and a bounded
    `InteractionHistory`. **Done.** 85 new tests. See
    `world/docs/INTERACTION_LAYER.md`.
12. **W10** — Live Command Center UI: unified into the existing React/
    Vite/FastAPI dashboard (`dashboard_src/`), not a separate app, per
    Krush's explicit direction — Office World is one more nav tab
    (`/world`), consuming Phase W8's `RenderFrame` wire format and Phase
    W9's `world.interaction.api` via new `api/world_api.py` (REST) and
    `api/world_ws.py` (WebSocket), both additively included into the
    existing FastAPI singleton. `main.py` now also warms up World and
    ticks the Simulation once per trading cycle, defensively wrapped so a
    World failure can never affect the trading engine (empirically
    proven, not just argued). First phase to touch Track A
    (`main.py`, `api/app.py`, `dashboard_src/`) — see
    `world/docs/LIVE_COMMAND_CENTER.md` for the full compatibility
    argument. **Done.**
13. **W11** — Live Operations Center: `telemetry/world_export.py` (new,
    Track A-side) calls existing read-only accessors — agent telemetry,
    subsystem heartbeats, circuit-breaker latency (now instrumented),
    active missions, portfolio drawdown/PnL/win-rate, and
    `events.event_bus`'s `get_recent()` — and writes them as the raw
    payloads Phase W4's readers expect. `main.py` schedules one export +
    `RuntimeManager.run_once()` per trading cycle, at the same cadence
    and with the same defensive wrapping as Phase W10's simulation tick.
    `portfolio.schema.json` gained an optional, additive `summary`
    object (real PnL/drawdown/win-rate, by explicit exception to the
    "no financial data" principle — see
    `docs/architecture/SEPARATION_POLICY.md` "Phase W11 amendment"),
    threaded all the way through to `WorldState.portfolio_summary`.
    CPU/RAM added via `psutil`, the one new dependency. All five Phase
    W4 readers now have live data; individual open exchange positions
    and true exchange/API-call latency remain future work (no verified
    read-only accessor was found for either — see
    `world/docs/LIVE_OPERATIONS_CENTER.md` "Known Gaps"). **Done.**
14. **W12** — Live Operations Workspace & Command Console: `world/workspace/`
    (10 feature modules: layout persistence, 7 named agent panels,
    operations dashboard top strip, notification dock with pin/read/
    clear, mission workspace grouped by status bucket, in-memory search,
    Ctrl+P quick nav, undo-only navigation history, logical performance
    overlay) plus `api.py`'s public facade — every feature reads only
    `world.runtime`/`world.simulation`/`world.interaction`, nothing new
    duplicates business logic or polls outside the existing pipeline.
    `api/workspace_api.py` (REST, `/api/workspace/*`) included
    additively into `api/app.py`; a new "Workspace" tab in the existing
    Office World page (`dashboard_src/.../WorkspacePanel.tsx`).
    Supersedes the narrower "W12 (proposed)" placeholder below (never
    built), which is carried forward as W13. Two documented gaps found
    and fixed along the way: `test_all_six_runtime_files_present`
    (Phase W4) needed updating for the new `workspace.json`, and a real
    pre-existing bug in Phase W10's own `NotificationsPanel.tsx` (wrong
    assumed shape for `InteractionNotification`) was caught and fixed —
    see `world/docs/OPERATIONS_WORKSPACE.md`. **Done.**
15. **W13 (proposed)** — Close the two gaps W11 documented rather than
    guessed: (a) a real mapping between `events/event_bus.py`'s
    subsystem agent names and the Phase W1 district `assignedAgents`
    codenames, so live events place themselves in the correct room
    instead of the neutral `command-hall` fallback; (b) a verified
    read-only accessor for currently-open exchange positions (as
    opposed to the most recent portfolio-decision-cycle figures W11
    wired), if one gets built in Track A. Both are additive,
    Track-B-visualization-quality improvements, not corrections to
    anything W11 shipped. Would also close Phase W12's own two honesty
    gaps (`OperationsSummary.mode`/`account_equity`).
