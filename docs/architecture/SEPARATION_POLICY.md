# Brain Bot V16 — Track Separation Policy

Status: **Active** (documentation-only policy, adopted 2026-07-28)

This document is the canonical definition of the two independent
development tracks in this repository. It changes no code, no tests,
no APIs, and no phase numbering — it formalizes a boundary that
governs all future planning and PRs. If wording in `CLAUDE.md`,
`README.md`, or `docs/architecture.md` ever diverges from this file,
this file wins.

---

## Why this exists

The repository contains both a production trading engine and a
visualization/dashboard layer (`dashboard_src/`, including
`src/game/`, `src/pages/world/`, and `public/assets/world/`). As both
continue to grow independently, it must stay structurally impossible
for a change to one to silently affect the other. This policy draws
that line explicitly, in writing, before it becomes a real conflict.

---

## Track A — Brain AI Trading System

**Purpose:** Production trading engine.

**Includes:**
- CEO Agent
- Portfolio Manager
- Risk Engine
- Execution Engine
- Journal
- Ensemble Learning
- Market Intelligence
- Binance Integration
- Database
- API
- Scheduler
- Recovery
- Monitoring

**Continues all existing phases** here — e.g. Phase 4B, Phase 4C,
Phase 5, Phase 6.

**Rule:** Never place any of the following inside this track unless
explicitly requested:
- sprites
- game assets
- world maps
- LPC characters
- animations
- NPC logic
- lore
- visual effects
- dashboard artwork

---

## Track B — Brain AI Command World

**Purpose:** Visualization layer only.

**Includes:**
- World
- Districts
- Characters
- LPC Sprites
- Portraits
- Buildings
- Dashboard Base UI
- Animations
- Lore
- Story
- Visual Effects
- Camera
- World Events

**Rule:** This track MUST NEVER modify:
- Trading Engine
- CEO logic
- Portfolio
- Risk Engine
- Execution
- Journal
- Database
- Exchange API
- Learning Engine

It is strictly a presentation layer.

---

## Communication contract

The Trading Engine **exports** data. Examples:

- `agent_status.json`
- `portfolio.json`
- `signals.json`
- `missions.json`
- `telemetry.json`
- `dashboard_state.json`

The Command World may **only read** these exported files. It must
never write back into the Trading Engine.

Likewise, the Trading Engine must never depend on:
- sprites
- animations
- world assets
- dashboard resources

This creates a one-way dependency:

```
Trading Engine
      |
      v
Stable JSON / API
      |
      v
Command World
```

Never the reverse.

---

## Phase W11 amendment (added 2026-08-03)

Phase W11 wires the Communication contract above to real data for the
first time (Phases W1–W10 built the pipeline; nothing produced real
output until W11). Two changes to this policy, both explicit and both
still one-way:

1. **Portfolio-wide read-only figures are now permitted to cross the
   boundary.** Individual positions still never carry raw notional
   size (`sizeLabel` stays a free-text display label — see
   `world/data/schemas/portfolio.schema.json`). But the optional
   top-level `summary` object in `portfolio.json` (`dailyPnl`,
   `floatingPnl`, `drawdown`, `winRate`, `avgRr`) is real, sourced
   verbatim from the trading engine's own existing read-only
   accessors — `portfolio.portfolio_history.get_latest_decisions()`
   and `journal.journal_v2.TradeJournalV2.get_daily_stats()` — never
   recomputed in `world/`. This is a deliberate exception to Track B's
   "presentation-only reflection, not a financial data feed"
   principle, made by explicit request; every other aspect of the
   one-way contract is unchanged.

2. **The export side of the contract now has an implementation**:
   `telemetry/world_export.py`, a new Track A-side module. It only
   ever *calls* existing accessors (see that file's own docstring for
   the complete list) and *writes* JSON — it never imports anything
   from `world/`, and `RuntimeManager.run_once()` (Track B) never
   imports anything from Track A. The dependency direction in the
   diagram above is unchanged; this module is the first concrete
   instance of the "Trading Engine exports data" box.

**Known gaps, documented rather than papered over:**

- Two vocabulary mismatches between Track A and Track B were
  discovered while building the exporter, with no existing mapping
  anywhere in the codebase: (a) `events/event_bus.py` publishers use
  real subsystem names (`RISK_MANAGER`, `SMC_ANALYST`, ...) that don't
  match the Phase W1 district `assignedAgents` codenames (`PRIMUS`,
  `BASTION`, ...); (b) `missions/mission_tracker.py`'s stage
  vocabulary (`SIGNAL_FOUND` → ... → `CLOSED`) doesn't match
  `missions.schema.json`'s status enum. Both are handled with a
  documented, conservative fallback in `telemetry/world_export.py`
  (events default to a neutral district; mission stages collapse to
  `proposed`/`active`) rather than a guessed 1:1 mapping. Building a
  real mapping is a candidate for a follow-up phase.
- No read-only accessor for the trading engine's currently-open
  exchange positions (a live list, as opposed to the most recent
  portfolio-decision-cycle figures above) was found. `positions` in
  `portfolio.json` remains empty until one is identified.

---

## Enforcement

- PRs touching Track A must not add sprite/animation/world-asset
  dependencies.
- PRs touching Track B must not import from Track A packages
  (`agents/`, `portfolio/`, `risk/`, `execution/`, `journal/`,
  `database/`, exchange-facing `api/` modules, `ml/`) — only from the
  exported JSON/API contract above.
- `CLAUDE.md`, `README.md`, and `docs/architecture.md` each carry a
  short pointer to this file rather than restating it, so there is one
  source of truth to keep current.

---

## Non-goals of this document

- No production code changed.
- No tests changed.
- No API changed.
- No phase numbering changed.
- No new dependencies introduced.
