# Brain AI Command World — Phase W1: Foundation Architecture

**Status:** Design/scaffolding only. Not implemented. Awaiting approval.
**Scope:** Everything below lives under `world/` in `brain-ai-trading-system`. Nothing in `agents/`, `execution/`, `portfolio/`, `journal/`, `risk/`, `api/`, `dashboard/`, or `main.py` is touched, referenced for writes, or assumed to change.

---

## 1. Architecture Report

Brain AI Command World is a **read-only visualization layer**. It observes the trading engine's state (via files/events it already emits, or a future thin adapter) and renders that state as a living city. It never calls into `execution/` or `risk/` and never issues orders. The boundary is one-directional:

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
    overview.md            # city-wide lore, cross-district narrative
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

| Character | Likely Agent Role (to confirm) | District | Animation Role |
|---|---|---|---|
| PRIMUS | Core/orchestrating intelligence | CEO Tower | Commands, oversees, idle-authoritative pose |
| BASTION | Risk / defense | Risk Fortress | Guards gates, raises shield on `emergency` |
| FORGE | Execution | Execution Forge | Hammers/builds during `working`, sparks on trade fill |
| WATCHER | Monitoring/surveillance | Market Intelligence Center | Scans horizon, idle-alert pose |
| SCRIBE | Journaling/logging | Journal Library | Writes continuously, files scrolls |
| PHOENIX | Recovery | Recovery Center | Rises/rebuilds after `emergency` state |
| ORACLE | Prediction/analysis | Research District | Studies charts, gestures during `working` |
| ECHO | Signal propagation/comms | Command Hall | Relays messages between districts |
| HERALD | Announcements/notifications | World Gateway | Blows horn on major events |
| CHAMELEON | Adaptive strategy | AI Council | Shifts posture/color with regime changes |
| CRUCIBLE | Testing/validation | Training Arena | Runs drills, sparring animations |
| MANDELBROT | Pattern/quant analysis | Simulation Lab | Draws fractal-like diagrams while `working` |
| SENTINEL | Security/auth | Risk Fortress | Stands watch at gate |
| GARDENER | Portfolio tending | Portfolio Garden | Prunes/waters, celebration on profit growth |
| WEBWEAVER | Data/API integration | Data Center | Weaves threads between server racks |
| CHRONOS | Timing/scheduling | Command Hall | Manages clock tower, ticks visibly |

Each character definition JSON captures **only presentation**: `spriteMeta`, `animationRole`, `dialogueRole`, `interactionRole`, and `district`. No file references trading logic or parameters.

**Standard animation states** (all characters): `idle`, `walking`, `working`, `celebration`, `emergency`. Equipment slots are generic and LPC-compatible: `head`, `body`, `weapon`, `accessory`, `aura` — populated later, empty in W1.

---

## 5. District Design

Each of the 14 districts gets a definition file with: `name`, `description`, `purpose`, `connectedDistricts`, `assignedAgents`, `visualTheme`, `musicTheme`, `futureExpansionHooks`. Example (abbreviated):

- **CEO Tower** — top-level oversight; connects to Command Hall, AI Council; agent PRIMUS; theme: glass spire, ambient orchestral.
- **AI Council** — strategy deliberation; connects to CEO Tower, Research District; agent CHAMELEON.
- **Research District** — analysis/prediction; agent ORACLE, MANDELBROT.
- **Risk Fortress** — defensive systems; agents BASTION, SENTINEL; stone/metal theme, tense low drone.
- **Execution Forge** — order execution reflection; agent FORGE; industrial theme, rhythmic percussion.
- **Portfolio Garden** — holdings visualized as growth; agent GARDENER; organic theme, pastoral music.
- **Market Intelligence Center** — external market watch; agent WATCHER.
- **Recovery Center** — post-drawdown healing; agent PHOENIX; soft rising theme.
- **Journal Library** — trade history; agent SCRIBE; quiet archival theme.
- **Data Center** — data pipelines; agent WEBWEAVER; server-hum ambient.
- **Training Arena** — backtesting/drills; agent CRUCIBLE.
- **Simulation Lab** — what-if scenarios; agent MANDELBROT.
- **World Gateway** — entry point/onboarding; agent HERALD.
- **Command Hall** — cross-district comms; agents ECHO, CHRONOS.

`connectedDistricts` forms a graph used later by the minimap; `futureExpansionHooks` are free-text notes like `"add sub-district: Options Wing"`.

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

- Phase W2: pick a renderer (likely PixiJS or Phaser for 2D city view given LPC assets) and build the read-only ingestion adapter.
- Phase W3: implement minimap + district navigation.
- Phase W4: LPC sprite integration using `spriteMeta` already defined.
- Phase W5: live event feed wired to real engine logs.
- Phase W6: relationship viewer, mission panel, notification center UI.
- Sub-districts and new characters can be added without breaking schemas, since arrays are additive.

## 8. Development Roadmap

1. **W1 (this phase):** architecture, schemas, lore skeleton, docs — no code execution, no assets.
2. **W2:** ingestion adapter design + choice of renderer, still no trading-code changes.
3. **W3:** static scene rendering with placeholder shapes (no sprites yet).
4. **W4:** asset pipeline activation (LPC sprites).
5. **W5:** live data wiring (read-only).
6. **W6:** full UI panel implementation.

## 9. Risks

- **Scope creep into trading code**: mitigated by hard folder boundary and this report's explicit exclusion list.
- **Schema churn**: mitigated by keeping W1 schemas minimal and additive-only.
- **Agent role mismatch**: character table above is inferred from names — needs Krush's confirmation against actual agent docs before lore is written as canon.
- **Termux constraints**: any future scripts should follow existing conventions (sequential commands, `printf` over heredoc, avoid heavy build tools where possible).
- **Engine lock-in temptation**: schemas must stay engine-neutral through W3 at minimum.

## 10. Suggested Next World Phase

**Phase W2 — Read-Only Ingestion Adapter Design.** Define exactly which existing engine outputs (log files, state files, or a lightweight event bus) can be safely read without touching `agents/`, `execution/`, etc., and design the adapter contract that populates `world/data/*.json` on a schedule. Still design-only, no renderer chosen yet.

---

*This document is the Phase W1 deliverable. No files have been added to the actual repository; no sprites, maps, or trading-code changes were made. Awaiting approval to scaffold these folders/files for real.*
