# Brain AI Command World — Phase W1: Foundation Architecture

**Status:** Implemented (W1, W1A). Superseded in part by Phase W2 — see notes
below. Extended, not superseded, by Phase W3, W4, W5, W6 (asset pipeline
half only), and W7.
**Scope:** Everything below lives under `world/` in `brain-ai-trading-system`. Nothing in `agents/`, `execution/`, `portfolio/`, `journal/`, `risk/`, `api/`, `dashboard/`, `dashboard_src/`, `main.py`, `config/`, `scanner/`, `pipeline/`, `telemetry/`, or `database/` is touched, referenced for writes, or assumed to change.

> **Phase W2 update (2026-07-29):** the visual theme described below (city,
> fortress, forge, castle-adjacent language) is retired. Brain AI Command
> World is permanently a modern office headquarters — see
> `docs/architecture/WORLD_OFFICE_POLICY.md` and `WORLD_DESIGN_LOCK.md`
> (canonical, "this document wins" on any conflict) and
> `world/docs/OFFICE_LAYOUT.md` / `world/docs/ROOM_SPECIFICATIONS.md` for the
> current department names, floors, and navigation graph. The tables in
> sections 4–5 below are kept for historical W1 design-intent context
> (why each character/district exists, what it reflects) — for current
> *names* and *theme*, the district/character JSON under
> `world/districts/definitions/` and `world/characters/definitions/` is the
> single source of truth.

> **Phase W3 update (2026-07-29):** the engine-agnostic renderer
> abstraction layer now exists at `world/frontend/` — see
> `world/frontend/README.md`. No renderer is chosen yet (still Phase
> W6); no sprites (Phase W6); no live data (Phase W4 designs the
> adapter, Phase W8 wires it). §7–8 below reflect the current phase
> numbering.

> **Phase W4 update (2026-07-31):** the read-only ingestion adapter now
> exists at `world/adapter/`, `world/readers/`, `world/watchers/`, and
> `world/runtime/` — see `world/docs/INGESTION_ADAPTER.md` and
> `world/docs/RUNTIME_DATA_FLOW.md`. `world/data/runtime/*.json` are real,
> pipeline-generated, schema-valid placeholders (all idle/empty — no
> `DataSource` points at a real engine file yet). Still no renderer
> (Phase W6), still no sprites (Phase W6).

> **Phase W5 update:** the World State Provider now exists at
> `world/runtime/{models,state_builder,state_cache,update_manager,
> relationship_resolver,state_validator,statistics,world_state_provider,
> api}.py` — see `world/docs/STATE_PROVIDER.md`. The six Phase W4 runtime
> files plus static W1/W2 canon now merge into one immutable, in-memory
> `WorldState`, cached and change-detected, with validation, relationship
> resolution, and statistics. Deliberately **not** bound to the Phase W3
> `WorldStateProvider` ABC or any renderer — that binding, plus folding in
> the Phase W6 Asset Pipeline work (built but never merged as its own
> branch), is now Phase W6 (Renderer Integration) per Krush's decision.
> The numbering itself changed here too: what earlier notes above call
> "Phase W5" (renderer pick + static scene) and "Phase W7" (live data
> wiring) are now **W6** and **W8** respectively — see
> `world/docs/roadmap.md` for the current canonical sequence.

> **Phase W6 update (retroactive):** the Asset Pipeline half of Phase W6
> merged — `world/data/assets/`, `world/data/interactions/`,
> `world/data/characters/spatial_placement.json`, and four concrete
> `AssetLoader`s — see `world/docs/ASSET_PIPELINE.md`. The Renderer
> Integration half (picking an engine, implementing the Phase W3
> `WorldStateProvider` ABC) did not happen and is renumbered to **Phase
> W8** below, per Krush's decision when Phase W7 was commissioned ahead of
> it.

> **Phase W7 update:** the Live Office Simulation layer now exists at
> `world/simulation/` — see `world/docs/SIMULATION.md`. Character
> behaviour (7 states) and room activity (6 states) are derived purely
> from Phase W5's `WorldState`; movement is abstract/logical (Dijkstra
> over the real Phase W2 navigation graph); events are metadata-only
> descriptors; a `Timeline` supports play/pause/resume/seek. No
> renderer-specific code, no trading/AI-decision logic invented. Built
> ahead of Phase W8 (Renderer Integration, still outstanding) since it
> only needs `WorldState` + Phase W6 asset metadata, not a renderer.
>
> **Phase W8 update:** Renderer Integration is done —
> `world/frontend/renderer/`. Concrete engine chosen: a backend
> scene-graph compiler targeting Phaser 3
> (`SceneGraphRenderer`), not a Python pixel-drawing library — `world/`
> stays engine-neutral; the actual pixel target is the project's
> browser frontend, wired up in Phase W10.
> `RenderWorldStateProvider` implements the Phase W3
> `WorldStateProvider` ABC (deferred since Phase W3's own docs said
> so) by projecting Phase W5's `WorldState` + Phase W7's
> `SimulationState` down to the flattened Phase W3 shape.
> `scene_builder`/`character_renderer`/`room_renderer`/`overlay_renderer`
> turn that into a JSON-serializable `RenderFrame` per room per tick,
> cached by `scene_cache.SceneCache`. Found and documented two real
> gaps rather than inventing around them: character-sprite ids have
> two disagreeing sources in this repo (only one resolves), and the
> five sprite animation states don't cover all seven Phase W7
> behaviour labels (`meeting`/`resting` fall back to
> `working`/`idle`, documented in one place). All 17 rooms (14
> departments + 3 circulation types) render against live data. See
> `world/docs/RENDERER.md`.
> **Real finding, documented in `SIMULATION.md` §4 rather than hidden:**
> the real navigation graph has no `lobby`/`hallway` nodes at all — only
> the 14 departments plus `elevator-floor-1/2/3` — even though Phase W6
> populated furniture into rooms literally named `lobby`/`hallway`. Not
> currently harmful (no real character's home room is either), but a
> genuine naming gap between Phase W2 and Phase W6.

> **Pre-W1 historical background (added 2026-08-02, Repository
> Stabilization phase):** one Track B commit predates this document and
> the W1-W8 numbering scheme entirely — `feat(world): performance v1`
> (commit `9ad1ab5`, 2026-07-19, branch `feature/world-performance-v1`,
> merged via PR #5 on 2026-07-20 — ten days *before* Phase W1's own
> first commit, `d74ba2c`, 2026-07-29). It covers code splitting, a
> minimap v2, an early portfolio dashboard, and store-equality
> performance work — groundwork that predates this document's own
> architecture, not part of the W1-W8 sequence, and not renumbered
> into it. Documented here because it was found unreferenced anywhere
> in Track B's documentation during a full-repository consistency
> audit; see `docs/REPOSITORY_STABILIZATION_REPORT.md`.
>
> **Editorial note (2026-08-02):** the Repository Stabilization phase's
> own draft "Phase W6 update" callout (which described Renderer
> Integration as still outstanding) is intentionally NOT included here
> — it was written before Phase W7/W8 had merged and is superseded by
> the W7/W8 callouts above, which are more complete and more current.
> Keeping both would have restated "renderer integration outstanding"
> right next to a callout confirming it's done.

---

## 1. Architecture Report

Brain AI Command World is a **read-only visualization layer**. It observes the trading engine's state (via files/events it already emits, or a future thin adapter) and renders that state as a living office headquarters (Phase W2). It never calls into `execution/` or `risk/` and never issues orders. The boundary is one-directional:

```
Trading Engine (agents/, execution/, risk/, ...) 
        │  (emits state/events — read only)
        ▼
world/data/  (snapshots, event log)
        ▼
world/scenes, world/ui  (render / narrate)
```

Because no game engine is chosen yet, everything is expressed as **engine-neutral JSON + plain documentation**. Any renderer (React, PixiJS, Phaser, Godot, Unity) consumes the same JSON contracts. This is the core design principle of Phase W1: data and lore are decoupled from presentation.

---

## 2. Folder Structure

```
world/
  README.md              # entry point, quick orientation
  WORLD.md                # full architecture doc (this report, refined)
  lore/
    overview.md            # building-wide lore, cross-department narrative
    districts/              # one lore file per district
    characters/              # one lore file per character
  assets/
    characters/              # (empty in W1 — reserved for future LPC sprites)
    districts/                # (empty in W1 — reserved for tilesets/backgrounds)
    audio/                     # (empty in W1 — reserved for music/sfx)
    manifest.schema.json       # describes how asset folders will be indexed later
  characters/
    definitions/               # one JSON file per character (non-visual: role, dialogue, slots)
  districts/
    definitions/                # one JSON file per district
  ui/
    specs/                      # one markdown spec per planned UI panel (design only)
  minimap/
    minimap.schema.json         # map node/edge schema (design only, no map yet)
  scenes/
    scene-manifest.schema.json  # how scenes reference districts/characters (design only)
  data/
    schemas/                    # world.json, districts.json, characters.json, etc.
    samples/                    # tiny example payloads validating each schema
  docs/
    architecture.md              # mirrors section 1 in depth
    roadmap.md
    coding-standards.md
    naming-conventions.md
    asset-conventions.md
  scripts/
    validate_schemas.py          # placeholder, validates JSON against schemas
  tests/
    test_schema_integrity.py
    test_character_uniqueness.py
    test_district_uniqueness.py
    test_relationship_validity.py
```

Rationale for deviations from the example: `lore/` is split into `districts/` and `characters/` subfolders so lore scales without one giant file; `data/schemas` vs `data/samples` separates contracts from examples; `ui/specs` holds one file per panel so panels can be approved/iterated independently.

---

## 3. JSON Schema Design

All schemas are drafted as **JSON Schema (draft 2020-12)** for tooling compatibility, and kept intentionally small in W1 — just enough structure to be stable, not exhaustive.

**world.json** — global state snapshot
```json
{
  "$id": "world.schema.json",
  "type": "object",
  "required": ["version", "timestamp", "engineStatus"],
  "properties": {
    "version": { "type": "string" },
    "timestamp": { "type": "string", "format": "date-time" },
    "engineStatus": { "type": "string", "enum": ["idle", "active", "recovering", "halted"] },
    "activeDistricts": { "type": "array", "items": { "type": "string" } }
  }
}
```

**districts.json**
```json
{
  "$id": "districts.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "name", "description", "purpose", "connectedDistricts", "assignedAgents", "visualTheme", "musicTheme"],
    "properties": {
      "id": { "type": "string" },
      "name": { "type": "string" },
      "description": { "type": "string" },
      "purpose": { "type": "string" },
      "connectedDistricts": { "type": "array", "items": { "type": "string" } },
      "assignedAgents": { "type": "array", "items": { "type": "string" } },
      "visualTheme": { "type": "string" },
      "musicTheme": { "type": "string" },
      "futureExpansionHooks": { "type": "array", "items": { "type": "string" } }
    }
  }
}
```

**characters.json**
```json
{
  "$id": "characters.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "agentRef", "displayName", "district", "spriteMeta", "dialogueRole"],
    "properties": {
      "id": { "type": "string" },
      "agentRef": { "type": "string", "description": "maps to existing agent name, e.g. PRIMUS" },
      "displayName": { "type": "string" },
      "district": { "type": "string" },
      "spriteMeta": {
        "type": "object",
        "properties": {
          "equipmentSlots": { "type": "array", "items": { "type": "string" } },
          "animations": {
            "type": "object",
            "properties": {
              "idle": { "type": "string" },
              "walking": { "type": "string" },
              "working": { "type": "string" },
              "celebration": { "type": "string" },
              "emergency": { "type": "string" }
            }
          }
        }
      },
      "dialogueRole": { "type": "string" },
      "animationRole": { "type": "string" },
      "interactionRole": { "type": "string" }
    }
  }
}
```

**relationships.json** — how characters/districts connect narratively
```json
{
  "$id": "relationships.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["from", "to", "type"],
    "properties": {
      "from": { "type": "string" },
      "to": { "type": "string" },
      "type": { "type": "string", "enum": ["reports-to", "collaborates-with", "informs", "guards", "supplies-data-to"] },
      "description": { "type": "string" }
    }
  }
}
```

**events.json** — reflected trading-state events (read-only, engine-authored)
```json
{
  "$id": "events.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "timestamp", "type", "district", "severity"],
    "properties": {
      "id": { "type": "string" },
      "timestamp": { "type": "string", "format": "date-time" },
      "type": { "type": "string" },
      "district": { "type": "string" },
      "agent": { "type": "string" },
      "severity": { "type": "string", "enum": ["info", "success", "warning", "critical"] },
      "message": { "type": "string" }
    }
  }
}
```

**missions.json** — narrative framing of engine objectives (flavor only, never control)
```json
{
  "$id": "missions.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "title", "district", "status"],
    "properties": {
      "id": { "type": "string" },
      "title": { "type": "string" },
      "description": { "type": "string" },
      "district": { "type": "string" },
      "status": { "type": "string", "enum": ["proposed", "active", "complete", "aborted"] }
    }
  }
}
```

**notifications.json**
```json
{
  "$id": "notifications.schema.json",
  "type": "array",
  "items": {
    "type": "object",
    "required": ["id", "timestamp", "message", "severity"],
    "properties": {
      "id": { "type": "string" },
      "timestamp": { "type": "string", "format": "date-time" },
      "message": { "type": "string" },
      "severity": { "type": "string", "enum": ["info", "success", "warning", "critical"] },
      "read": { "type": "boolean" }
    }
  }
}
```

---

## 4. Character System Design

Characters wrap **existing agents** — no responsibility redesign, only presentation. Suggested mapping (roles inferred from naming; Krush should confirm/correct against actual agent responsibilities before lore is finalized):

| Character | Likely Agent Role (to confirm) | Department (Phase W2) | Animation Role (Phase W2) |
|---|---|---|---|
| PRIMUS | Core/orchestrating intelligence | CEO Office | Authoritative oversight from the corner office |
| BASTION | Risk / defense | Risk Department | Raises an alert banner on `emergency` |
| FORGE | Execution | Trading Floor | Types rapidly at the desk during fills |
| WATCHER | Monitoring/surveillance | Market Intelligence Center | Monitors the screen wall |
| SCRIBE | Journaling/logging | Journal Department | Logs entries continuously at the terminal |
| PHOENIX | Recovery | Recovery Center | Leads the recovery briefing after an `emergency` |
| ORACLE | Prediction/analysis | Research Lab | Reviews model output on monitor |
| ECHO | Signal propagation/comms | Command Center | Relays signals across departments |
| HERALD | Announcements/notifications | Reception | Greets visitors at the front desk |
| CHAMELEON | Adaptive strategy | AI Department | Updates the strategy whiteboard as regime shifts |
| CRUCIBLE | Testing/validation | Training Room | Runs test sessions |
| MANDELBROT | Pattern/quant analysis | Simulation Room | Runs scenario models on screen while `working` |
| SENTINEL | Security/auth | Risk Department | Monitors the access log at the desk |
| GARDENER | Portfolio tending | Garden | Waters plants, reviews the holdings board |
| WEBWEAVER | Data/API integration | Server Room | Checks server racks, monitors dashboards |
| CHRONOS | Timing/scheduling | Command Center | Manages the wall clock and schedule board |

Each character definition JSON captures **only presentation**: `spriteMeta`, `animationRole`, `dialogueRole`, `interactionRole`, and `district`. No file references trading logic or parameters.

**Standard animation states** (all characters): `idle`, `walking`, `working`, `celebration`, `emergency`. Equipment slots are generic and LPC-compatible: `head`, `body`, `tool`, `accessory`, `statusGlow` (Phase W2 — renamed from `weapon`/`aura` to match office character design; no armor/weapon slots per `WORLD_OFFICE_POLICY.md`) — populated later.

---

## 5. District Design

Each of the 14 districts gets a definition file with: `name`, `description`, `purpose`, `connectedDistricts`, `assignedAgents`, `visualTheme`, `musicTheme`, `futureExpansionHooks`. Example (abbreviated, **Phase W2 office names**):

- **CEO Office** — top-level oversight; connects to Command Center, AI Department; agent PRIMUS; theme: glass corner office, city view.
- **AI Department** — strategy deliberation; connects to CEO Office, Research Lab; agent CHAMELEON.
- **Research Lab** — analysis/prediction; agent ORACLE, MANDELBROT.
- **Risk Department** — defensive systems; agents BASTION, SENTINEL; glass office, risk dashboards.
- **Trading Floor** — order execution reflection; agent FORGE; open trading floor, multi-monitor desks.
- **Garden** — holdings visualized as growth; agent GARDENER; glass atrium, indoor plants.
- **Market Intelligence Center** — external market watch; agent WATCHER.
- **Recovery Center** — post-drawdown healing; agent PHOENIX; calm lounge theme.
- **Journal Department** — trade history; agent SCRIBE; records room, digital archive wall.
- **Server Room** — data pipelines; agent WEBWEAVER; server racks, cool blue LED.
- **Training Room** — backtesting/drills; agent CRUCIBLE.
- **Simulation Room** — what-if scenarios; agent MANDELBROT.
- **Reception** — entry point/onboarding; agent HERALD.
- **Command Center** — cross-department comms; agents ECHO, CHRONOS.

`connectedDistricts` forms a graph used later by the minimap (materialized in Phase W2 as `world/data/navigation/graph.json`); `futureExpansionHooks` are free-text notes like `"sub-department hook for X (Phase W3+)"`.

---

## 6. World Data Flow

```
Engine state (files/logs the engine already produces)
        │
        ▼
world/data/ingestion (future phase — a read-only adapter, not built in W1)
        │
        ▼
world.json / events.json / notifications.json  (snapshots)
        │
        ▼
Renderer (any engine) reads schemas → animates districts/characters
        │
        ▼
UI panels (Minimap, Inspector, Activity Feed, etc.) present state to Krush
```

No arrow ever points back into the engine. `missions.json` is narrative flavor derived from read-only state, not a control channel.

---

## 7. Future Expansion Plan

- Phase W2 (**done**): retcon to modern office HQ theme; add `world/data/layout`, `world/data/characters` (placement), `world/data/navigation` as a spatial layer.
- Phase W2.1 (**done**): documentation synchronization — this document, roadmap, lore, ui/specs.
- Phase W3 (**done**): renderer foundation — engine-agnostic abstraction layer under `world/frontend/` (13 interfaces + concrete state-only Scene/Camera/Viewport/AssetRegistry/RoomType). No renderer chosen, no sprites, no live data.
- Phase W4 (**done**): read-only ingestion adapter — `world/readers/` (5 generic readers behind a `DataSource`/`Reader` split), `world/watchers/` (2 change-detection strategies), `world/adapter/` (orchestration), `world/runtime/` (`RuntimeManager` + hash-based `SnapshotCache`, writes only `world/data/runtime/`). No `DataSource` points at a real engine path yet.
- Phase W5 (**done**): World State Provider — `world/runtime/{models,state_builder,state_cache,update_manager,relationship_resolver,state_validator,statistics,world_state_provider,api}.py`. Merges the six Phase W4 runtime files with static W1/W2 canon into one immutable, in-memory `WorldState`. Deliberately not bound to the Phase W3 `WorldStateProvider` ABC or any renderer — see `world/docs/STATE_PROVIDER.md` §9.
- Phase W6 (**asset pipeline half done, renderer half renumbered to W8**): four concrete `AssetLoader`s (OpenGameArt, LPC, Kenney, Custom) implementing `world/frontend/interfaces/asset_loader.py`, asset manifest/packs/compatibility layer, and full furniture + decoration population of every room plus sprite + spatial placement for every character — see `world/docs/ASSET_PIPELINE.md`.
- Phase W7 (**done**): Live Office Simulation — `world/simulation/`: 7 character behaviours + 6 room activity levels derived purely from Phase W5's `WorldState`, abstract logical movement (Dijkstra over the real Phase W2 navigation graph), metadata-only event descriptors, a play/pause/resume/seek `Timeline`, and the 8-function `world.simulation.api`. No renderer-specific code. See `world/docs/SIMULATION.md`.
- Phase W8 (**done**): Renderer Integration (the Phase W6 half that never happened) — `world.frontend.renderer.renderer.SceneGraphRenderer` implements the Phase W3 `Renderer` ABC as a backend scene-graph compiler targeting Phaser 3; `RenderWorldStateProvider` implements the Phase W3 `WorldStateProvider` ABC by projecting Phase W5 + W7 state down to the renderer-facing shape; all 17 real rooms render end to end. See `world/docs/RENDERER.md`. *(This entry was not updated when W8 actually merged — corrected now, alongside the W9 update below, rather than left to drift further.)*
- Phase W9 (**done**): Interactive Command Center — `world/interaction/`: selection/hover/inspector/focus/timeline-seek/notification-center/search/filters/command-dispatch/history, all read-only over Phase W5+W7 state plus the Phase W8 camera controller. No trading-code, `dashboard/`, or renderer-pixel changes. See `world/docs/INTERACTION_LAYER.md`.
- Phase W10: Live Command Center UI — implement the full UI panel set already specified in `world/ui/specs/` (minimap, inspectors, activity feed, notification center, relationship viewer, time control, simulation controls) as an actual browser frontend (React + Vite + Phaser 3) consuming the Phase W8 `RenderFrame` wire format and the Phase W9 interaction API.
- Phase W11: Real-time Operations Center — point real `DataSource` instances (Phase W4) at whatever the trading engine actually emits and schedule `RuntimeManager.run_once()` (a `Watcher`-gated loop or fixed interval), so the Phase W10 UI reflects live engine state instead of the current idle placeholders.
- Sub-departments and new characters can be added without breaking schemas, since arrays are additive.

## 8. Development Roadmap

1. **W1:** architecture, schemas, lore skeleton, docs — no code execution, no assets.
2. **W1A:** materialize the folder structure and placeholder files in-repo.
3. **W2 (done):** retcon fantasy theme to modern office HQ; add layout/placement/navigation data layer.
4. **W2.1 (done):** documentation synchronization across `WORLD.md`, roadmap, lore, and ui/specs.
5. **W3 (done):** renderer foundation — abstraction layer, no engine chosen.
6. **W4 (done):** read-only ingestion adapter — generic readers/watchers/adapter/runtime pipeline, no real source wired.
7. **W5 (done):** World State Provider — backend-only in-memory `WorldState`, caching, validation, relationship resolution, statistics.
8. **W6 (asset pipeline done, renderer half renumbered to W8):** four concrete `AssetLoader`s, asset manifest/packs, compatibility layer, full office population.
9. **W7 (done):** Live Office Simulation — character behaviour, room activity, movement, event descriptors, timeline, simulation API, statistics.
10. **W8 (done):** Renderer Integration — `WorldStateProvider` ABC binding, Phaser-3-targeting scene-graph renderer, static scene rendering against live W5+W7 data.
11. **W9 (done):** Interactive Command Center — selection, hover, inspector, focus/camera commands, timeline seek/replay, notification center, search, filters, event bus, interaction history.
12. **W10:** Live Command Center UI — the full UI panel set from `world/ui/specs/` as an actual browser frontend.
13. **W11:** Real-time Operations Center — live `DataSource` wiring so W10's UI reflects real engine state.

## 9. Risks

- **Scope creep into trading code**: mitigated by hard folder boundary and this report's explicit exclusion list.
- **Schema churn**: mitigated by keeping W1 schemas minimal and additive-only.
- **Agent role mismatch**: character table above is inferred from names — needs Krush's confirmation against actual agent docs before lore is written as canon.
- **Termux constraints**: any future scripts should follow existing conventions (sequential commands, `printf` over heredoc, avoid heavy build tools where possible).
- **Engine lock-in temptation**: schemas and Phase W3 interfaces must stay engine-neutral through W8 (renderer choice) at minimum.
- **Journal has no schema yet**: `JournalReader` (Phase W4) returns `JournalEntry` dataclasses but there is no `journal.schema.json` / `world/data/runtime/journal.json` — the Phase W4 task's own output contract only names six runtime files and none is a journal snapshot. Flagged, not fixed, in Phase W4 — see Compatibility Report in the Phase W4 delivery message.
- **Static canon re-read on every rebuild**: `StateBuilder` re-reads all district/character definitions and `placement.json` from disk on every `build()` call, even though that data never changes at runtime — the real Part L benchmark (`world/docs/STATE_PROVIDER.md` §8) shows rebuild cost staying around 2.7–5ms regardless of N rather than trending toward near-zero, because of this. Not a correctness bug, but a real optimization opportunity for a future phase.
- **Navigation graph / room-population naming gap**: `world/data/navigation/graph.json` (Phase W2) has no `lobby`/`hallway` nodes — only the 14 departments plus `elevator-floor-1/2/3` — even though the Phase W6 asset pipeline populated furniture into rooms literally named `lobby`/`hallway`. Not currently harmful (no real character's home room is either, and neither Phase W8's renderer nor Phase W9's interaction layer route a character or camera through the lobby), but should still be reconciled before a future phase needs to.

## 10. Suggested Next World Phase

**Phase W10 — Live Command Center UI.** Implement the full UI panel set already specified in `world/ui/specs/` (minimap, agent inspector, district inspector, activity feed, notification center, relationship viewer, time control, simulation controls) as an actual browser frontend — React + Vite + Phaser 3, per the compatibility list this repo commits to. It consumes two already-complete backends: Phase W8's `RenderFrame` wire format (`world/frontend/renderer/render_state.py`) for what to draw, and Phase W9's `world.interaction.api` for what happens on click/hover/search/filter. No new backend logic should be needed for W10 itself — it's a rendering and wiring phase, same shape as W8 was for the scene graph.

---

*This document was the Phase W1 deliverable; W1 and W1A have since been*
*implemented. Phase W2 (office HQ retcon + layout/navigation layer),*
*Phase W2.1 (this document's synchronization), Phase W3 (renderer*
*foundation, `world/frontend/`), Phase W4 (read-only ingestion*
*adapter, `world/adapter/` `world/readers/` `world/watchers/`*
*`world/runtime/`), Phase W5 (World State Provider,*
*`world/runtime/{models,state_builder,state_cache,update_manager,*
*relationship_resolver,state_validator,statistics,world_state_provider,*
*api}.py`), the Asset Pipeline half of Phase W6 (furniture/decoration/*
*character-sprite metadata, four `AssetLoader`s, see*
*`world/docs/ASSET_PIPELINE.md`), Phase W7 (Live Office Simulation,*
*`world/simulation/`, see `world/docs/SIMULATION.md`), Phase W8*
*(Renderer Integration, `world/frontend/renderer/`, see*
*`world/docs/RENDERER.md`), and Phase W9 (Interactive Command Center,*
*`world/interaction/`, see `world/docs/INTERACTION_LAYER.md`) are also*
*complete — see `docs/architecture/WORLD_OFFICE_POLICY.md`,*
*`WORLD_DESIGN_LOCK.md`, `world/docs/INGESTION_ADAPTER.md`,*
*`world/docs/STATE_PROVIDER.md`, `world/docs/SIMULATION.md`,*
*`world/docs/RENDERER.md`, and `world/docs/INTERACTION_LAYER.md` for*
*current canon. No trading-code changes have been made through Phase W9.*
*A browser-rendered UI (Phase W10) and live engine data (Phase W11)*
*remain outstanding.*
