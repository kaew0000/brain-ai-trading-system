# Brain AI Command World — Phase W1: Foundation Architecture

**Status:** Implemented (W1, W1A). Superseded in part by Phase W2 — see note
below.
**Scope:** Everything below lives under `world/` in `brain-ai-trading-system`. Nothing in `agents/`, `execution/`, `portfolio/`, `journal/`, `risk/`, `api/`, `dashboard/`, or `main.py` is touched, referenced for writes, or assumed to change.

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
- Phase W3: pick a renderer (React Canvas, PixiJS, Phaser, Godot, or Unity — all equally supported by the schemas) and build the read-only ingestion adapter.
- Phase W4: static scene rendering with placeholder shapes using the Phase W2 layout/navigation data.
- Phase W5: office-appropriate sprite integration using `spriteMeta` already defined (no LPC weapon/armor slots — see §4).
- Phase W6: live event feed wired to real engine logs.
- Phase W7: relationship viewer, mission panel, notification center UI.
- Sub-departments and new characters can be added without breaking schemas, since arrays are additive.

## 8. Development Roadmap

1. **W1:** architecture, schemas, lore skeleton, docs — no code execution, no assets.
2. **W1A:** materialize the folder structure and placeholder files in-repo.
3. **W2 (done):** retcon fantasy theme to modern office HQ; add layout/placement/navigation data layer.
4. **W2.1 (done):** documentation synchronization across `WORLD.md`, roadmap, lore, and ui/specs.
5. **W3:** ingestion adapter design + choice of renderer, still no trading-code changes.
6. **W4:** static scene rendering with placeholder shapes (no sprites yet).
7. **W5:** asset pipeline activation (office-appropriate sprites).
8. **W6:** live data wiring (read-only).
9. **W7:** full UI panel implementation.

## 9. Risks

- **Scope creep into trading code**: mitigated by hard folder boundary and this report's explicit exclusion list.
- **Schema churn**: mitigated by keeping W1 schemas minimal and additive-only.
- **Agent role mismatch**: character table above is inferred from names — needs Krush's confirmation against actual agent docs before lore is written as canon.
- **Termux constraints**: any future scripts should follow existing conventions (sequential commands, `printf` over heredoc, avoid heavy build tools where possible).
- **Engine lock-in temptation**: schemas must stay engine-neutral through W3 at minimum.

## 10. Suggested Next World Phase

**Phase W3 — Read-Only Ingestion Adapter Design.** Define exactly which existing engine outputs (log files, state files, or a lightweight event bus) can be safely read without touching `agents/`, `execution/`, etc., and design the adapter contract that populates `world/data/*.json` on a schedule. Still design-only, no renderer chosen yet.

---

*This document was the Phase W1 deliverable; W1 and W1A have since been*
*implemented. Phase W2 (office HQ retcon + layout/navigation layer) and*
*Phase W2.1 (this document's synchronization) are also complete — see*
*`docs/architecture/WORLD_OFFICE_POLICY.md`, `WORLD_DESIGN_LOCK.md`, and*
*`world/docs/OFFICE_LAYOUT.md` for current canon. No sprites, renderer, or*
*trading-code changes have been made through Phase W2.1.*
