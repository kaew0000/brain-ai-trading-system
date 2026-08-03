# Live Command Center UI — Phase W10

Status: implemented, as the **unified** browser interface, per Krush's
explicit direction — not a separate World dashboard. Office World is one
more tab inside the same existing React/Vite/FastAPI dashboard that
already serves Trading, AI Agents, Portfolio, and everything else.

## 1. Architecture Report

This phase touches Track A for the first time in the project
(`main.py`, `api/app.py`, `dashboard_src/`), on Krush's explicit
instruction to unify World into the existing dashboard rather than
building a second one. Given the stakes (`main.py` runs a live automated
trading bot), every Track A change here is:

- **Purely additive** — new files, or a small number of new lines in
  existing files, never a rewrite of existing logic.
- **Defensively wrapped** — `main.py`'s two new functions
  (`_initialize_world_runtime`, `_tick_world_simulation`) catch every
  exception and log-and-continue; proven empirically (not just argued) by
  monkeypatching `world.runtime.api.get_world_state` to raise and
  confirming the bot still starts (see Compatibility Report).
- **Verified against the full existing suite before and after** — Track A
  Python: 1915/1915 (was 1885 before this phase's 30 new
  `tests/test_world_api.py` / `tests/test_world_ws.py`), run three times
  after successive changes. Track A frontend: no pre-existing test
  regressions (the only prior frontend tests were in the old World page
  being replaced — see §9).

```
Trading Engine (unchanged)
    |  (existing components dict)
    v
main.py  -- _initialize_world_runtime() -- world.runtime + world.simulation (warm-up, read-only)
    |  -- schedule.every(LOOP_INTERVAL).do(_tick_world_simulation)  -- world.simulation.api.step()
    v
api/app.py (existing FastAPI singleton, unchanged elsewhere)
    |  + app.include_router(world_api.router)     /api/world/*
    |  + app.include_router(world_ws.router)      /ws/world
    |  + one line in the existing _broadcast_loop(): await world_ws.check_and_broadcast()
    v
dashboard_src (existing React/Vite app, unchanged elsewhere)
    |  + one NAV entry: Office World -> /world (already-existing SPA route)
    |  + src/pages/world/ replaced entirely (see Section 9)
    v
One browser tab: Trading, AI Agents, Office World, Portfolio, ... (already unified -- see Section 2)
```

## 2. UI Architecture

"Unified" here means literally the same points as everywhere else in this
codebase: one FastAPI app (`api/app.py`), one built SPA (`dashboard_src` ->
`dashboard/dist`), one nav sidebar (`Layout.tsx`). Office World is
`dashboard_src/src/pages/world/WorldPage.tsx`, reached via the **same**
`/world` route the old V15 page used (no new route registration needed --
the SPA catch-all in `api/app.py` already served `/world`; it just wasn't
in the nav sidebar before). Internally it has 4 tabs: **Office** (scene +
room list + inspector), **Timeline**, **Alerts**, **Settings** -- see
Section 9 for why Timeline/Alerts/Settings are sub-tabs of Office World
rather than new top-level dashboard tabs.

## 3. Public API Design

Backend: `api/world_api.py` (REST, `/api/world/*`) and `api/world_ws.py`
(`/ws/world`), both thin wrappers around the four already-public Track B
APIs -- `world.runtime.api`, `world.simulation.api`, `world.interaction.api`,
and this phase's new `world.frontend.renderer.api` (see Section 11's
compatibility note on why that one file was missing until now). Every
route is one call into one of those four modules; nothing here contains
simulation, movement, or trading logic of its own.

Frontend: `dashboard_src/src/pages/world/api.ts` -- a small `worldApi`
object of REST calls plus `wsWorld` (the shared `ManagedWS` class every
other dashboard channel already uses, `src/lib/api.ts`).

## 4. Window System Design

No custom window manager, docking system, or Qt/Electron -- this dashboard
is browser tabs + React component tabs, matching the rest of the app
exactly (React Router pages, no floating/dockable panels anywhere in this
codebase). The original W10 brief's "Window Manager, Dockable panels,
Window layout persistence" are scoped down to what's actually consistent
with the rest of this dashboard: tab navigation (`WorldPage.tsx`'s
internal 4 tabs) plus one `localStorage`-persisted preference (simulation
speed, `SettingsPanel.tsx`) -- see Section 9's scoping note.

## 5. Overlay Design

Room activity (`quiet`/`busy`/`meeting`/`alert`/`critical`/`celebration`)
and character behaviour (7 states) are both color-coded -- see
`sceneMapping.ts`'s `ACTIVITY_COLORS`/`BEHAVIOR_COLORS`. The Phaser canvas
(`OfficeScene.tsx`) draws these as colored circles/rectangles rather than
sprite images, since no PNG assets exist yet (Phase W6 built asset
*metadata* only -- see `world/docs/ASSET_PIPELINE.md`). This is a real,
data-driven rendering of the actual `RenderFrame` (Phase W8) -- not a mock.

## 6. Timeline Integration

`TimelinePanel.tsx` -> `/api/world/timeline*` -> directly the Phase W7
`Timeline` object (`world.simulation.api.get_timeline()`), for
play/pause/resume/seek. `jump_to_event` (needs `CommandDispatcher`'s
event-publishing) goes through `world.interaction.api.dispatch` instead --
see `api/world_api.py`'s own comment for why the split.

## 7. Notification Design

`NotificationsPanel.tsx` -> `/api/world/notifications` ->
`world.interaction.api.get_notifications()` (Phase W9's `NotificationCenter`).
Polled every 3s (matches the dashboard's existing polling cadence for
non-realtime panels); `/ws/world` pushes room/character activity in
realtime instead, since notifications don't yet have their own push
channel -- a reasonable future addition (see Section 14... see Section 11).

## 8. Migration Notes

Nothing in W1-W9 was modified. The one Track A behavior change,
end-to-end tested: `main.py` now also warms up World and ticks the
simulation once per trading cycle -- both no-ops from the trading engine's
perspective (read `world.runtime`, never `components`/`agents`/
`execution`). `api/app.py` gained two `include_router` calls and one line
in the existing broadcast loop; every existing route, test, and behavior
is unchanged (1915/1915 passing, same count plus this phase's new tests
as the only delta).

## 9. Scoping decisions (documented, not silently narrowed)

- **The old V15 World page was replaced entirely**, per Krush's explicit
  decision -- all files under the old `dashboard_src/src/pages/world/`
  (`WorldScene.ts`, `Player.ts`, `NPC.ts`, lighting/particle/pathfinding
  systems, the old Zustand store, e2e specs) are gone. Its 32 tests are
  gone with it; this phase's 16 new frontend tests cover the new
  `sceneMapping.ts` + `api.ts` (the two genuinely unit-testable layers --
  Phaser canvas rendering itself isn't tested in jsdom, same limitation
  the old suite had for its own Phaser scene).
- **"Timeline", "Alerts", "Settings" are sub-tabs of Office World**, not
  new top-level dashboard tabs. "AI Agents", "Trading", "Portfolio" already
  exist as their own pages (Agent Floor, Overview/Commander, Portfolio) and
  weren't touched -- the unification requirement ("no duplicate dashboards")
  is satisfied by them already living in the same app, not by renaming or
  merging them into Office World.
- **"Window Manager" / "dockable panels"** are scoped down to this
  dashboard's actual, consistent pattern (React Router tabs), not a new
  floating-window system nothing else in this codebase has -- see Section 4.
- **A pre-existing, unrelated bug was fixed**: `dashboard_src/vite.config.ts`
  had `react`/`react-dom`/`framer-motion`/`zustand` duplicated across two
  manual-chunk groups (`ui-vendor` and a fully redundant `react-vendor`),
  which made `npm run build` fail on **completely unmodified `main`**
  (verified independently -- see Compatibility Report). Fixed by removing
  the redundant group; without this the dashboard couldn't be built at
  all, blocking this phase's own deliverable as well as everything else.

## 10. Risks

- **First-ever Track A changes in this project.** Mitigated by: additive-
  only diffs, defensive wrapping with an empirical failure-path test, full
  before/after suite runs (backend + frontend), and this document's
  explicit scoping notes.
- **No PNG sprite/tile assets exist** (Phase W6 gap, not new to this
  phase) -- `OfficeScene.tsx` draws shapes, not art. Real visuals need
  actual asset files, a separate future concern.
- **`lobby`/`hallway` navigation gap** (flagged in Phase W7) is unaffected
  by this phase -- Office World's room list still only shows real
  department ids plus whatever `world.simulation.api` reports.
- **Notifications have no push channel yet** -- polled, not realtime (see
  Section 7). Low risk (3s staleness), documented rather than silently
  accepted.
- **`/ws/world` heartbeat/dedup state is module-level**, same pattern
  `portfolio_ws.py` already uses -- same known tradeoff (shared across all
  connections, not per-connection), not new to this phase.

## 11. Future W11 Proposal

**Phase W11 -- Real-Time Operations Center.** Point real `DataSource`
instances (Phase W4) at whatever the trading engine actually emits (still
idle/placeholder today), add a push channel for notifications, and
consider whether Office World's scene view would benefit from real asset
art now that a full render pipeline exists end-to-end (backend -> REST/WS ->
Phaser canvas) to actually display it.
