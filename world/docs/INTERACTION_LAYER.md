# Interaction Layer (Phase W9)

## 1. Purpose

`world/interaction/` makes the office interactive: select a room,
character, department, furniture, decoration, or event; hover for a
quick status; open a full inspector; move the camera; scrub the
simulation timeline; read notifications; search and filter. Every part
of it is **read-only** — nothing here mutates `world.runtime` or
`world.simulation` state, and nothing here imports `agents/`,
`execution/`, `portfolio/`, `learning/`, `risk/`, `exchange/`, or
`dashboard/`. The only two calls with any side effect at all are
`pause_simulation`/`resume_simulation`, which delegate to the same
`world.simulation.api.pause`/`resume` Phase W7 already exposed as
read-only-from-the-trading-engine's-perspective.

## 2. Architecture

```
world.runtime.api (W5)  ---\
                             +--> world.interaction.* --> world.interaction.api
world.simulation.api (W7) --/            |
                                          v
                          world.frontend.camera (W8, via FocusManager)
```

The interaction layer is a **second consumer** of Phase W5 + W7 state,
parallel to the Phase W8 renderer — not downstream of it. It does not
depend on a live `SceneGraphRenderer` instance existing; `FocusManager`
loads its own `ReferenceCameraController`, from the same real room-anchor
data (`world/data/layout/rooms.json`) the renderer's camera uses,
independent of whether any renderer has actually run.

| Module | Responsibility |
|---|---|
| `models.py` | Frozen dataclasses: `Selection`, `HoverInfo`, `InspectorReport`, `HistoryEntry`, `InteractionNotification`, `CommandResult` |
| `selection_manager.py` | `SelectionManager` — validates a selection against real ids |
| `hover_manager.py` | `HoverManager` — lightweight per-target hover data |
| `inspector.py` | `build_inspector_report()` — the full Inspector Panel |
| `focus_manager.py` | `FocusManager` — wraps Phase W8's `ReferenceCameraController` |
| `timeline_controller.py` | `TimelineController` — seek/replay/jump-to-event over Phase W7's `Timeline` |
| `notification_center.py` | `build_notifications()` — derived only from `SimulationState` |
| `search.py` | `search()` — substring search over rooms/agents/events |
| `filters.py` | Pure filter functions over `WorldState`/`SimulationState` |
| `command_dispatcher.py` | `CommandDispatcher` — the 9 read-only commands |
| `interaction_events.py` | `EventBus` — the six interaction event types |
| `interaction_history.py` | `InteractionHistory` — bounded log of selections/commands |
| `tooltip.py` | `build_tooltip_text()` — formats a `HoverInfo` for display |
| `api.py` | The public surface most callers should use (module-level shared instances) |

## 3. Selection Model

Six selectable kinds: `room`, `character`, `department`, `furniture`,
`decoration`, `event`. `room` and `department` resolve against the same
id space — in this codebase, departments *are* rooms (see
`world/docs/OFFICE_LAYOUT.md`) — kept as two labels only because a
caller may want to know which noun the user actually clicked.

`SelectionManager.select(kind, target_id)` validates before accepting:

- `room`/`department` — must exist in `world.runtime.api.get_world_state().rooms`
- `character` — must exist in `.agents`
- `furniture`/`decoration` — must be a real `instanceId` from
  `world/data/assets/room_assets.json`'s per-room placement lists
- `event` — must exist in `world.simulation.api.get_current_events()`
  (events are transient; only the current tick's events, or ones still
  retained in `Timeline` history, are selectable)

An unknown id raises `UnknownSelectionTargetError` rather than silently
accepting a selection that resolves to nothing.

## 4. Inspector Panel

`build_inspector_report(kind, target_id)` merges three sources per
target:

- **Identity** (Phase W5 `world.runtime.api`): name, current room,
  static status, occupants, active missions.
- **Current behaviour** (Phase W7 `world.simulation.api`): the current
  tick's character behaviour or room activity level.
- **History** (Phase W7 `Timeline`, via the Phase W9 addition
  `world.simulation.api.get_timeline()`): every retained tick in which
  this target appeared, most recent last, bounded to
  `DEFAULT_HISTORY_LIMIT = 20` entries by default.
- **Relationships** (Phase W5 `relationship_resolver`): department
  ownership, folded into `linked_runtime_data` for room/department
  reports.

Furniture/decoration/event selections get an identity-only report — they
have no runtime/simulation record of their own to merge in.

`Timeline` deliberately exposes no "give me every recorded state"
accessor — only `current()`/`seek()`, one at a time. Reading its private
`_records` list (via `getattr`, not direct attribute access) is a
documented, intentional exception: duplicating that storage in a second
list kept in sync on every `step()` would be a second source of truth
for the same history, which is worse.

## 5. Timeline (Seek, Replay, Pause, Resume, Jump to Event)

`TimelineController` wraps `world.simulation.api.get_timeline()` and adds
exactly one thing `Timeline` doesn't have: `jump_to_event(event_id)`,
since an `EventDescriptor` carries no tick number of its own — it's only
ever seen attached to the `SimulationState` that produced it.
`jump_to_event` scans retained history for the tick that produced the
named event and delegates to `Timeline.seek()`.

This class does not wrap `SimulationEngine.step()`/`pause()`/`resume()`
themselves; those live in `CommandDispatcher`, which is also responsible
for publishing the matching `EventBus` events.

## 6. Notification System

The phase brief specifies: **"Notifications consume SimulationState
only."** `build_notifications()` therefore does *not* read Phase W5's
own `NotificationState` (from `world/data/runtime/notifications.json`),
even though that would be the more obvious source — every
`InteractionNotification` is derived from `SimulationState.events`
(`EventDescriptor.kind`) and `SimulationState.rooms`
(`RoomActivityState.activity`) alone.

`SimulationState` has no `category` field of its own, so the six brief
categories (Emergency, Meeting, Alert, Mission, Celebration, System
status) are this phase's own mapping, made explicit rather than left
implicit:

| Source | Value | Category |
|---|---|---|
| Event kind | `risk_alert` | alert |
| Event kind | `system_recovery` | system_status |
| Event kind | `portfolio_growth` | celebration |
| Event kind | `trade_opened` / `trade_closed` | mission |
| Event kind | `notification` (generic) | system_status |
| Room activity | `critical` | emergency |
| Room activity | `meeting` | meeting |
| Room activity | `celebration` | celebration |

`trade_opened`/`trade_closed` -> `mission` is the least certain mapping
here: `SimulationState` carries no actual mission identity, so this is
"closest available reading of ongoing mission-like activity," not a
verified link to `world.runtime.models.MissionState`. Flagged for
whoever builds Phase W10's actual notification UI to reconsider if a
truer mission link is wanted.

## 7. Event Flow

Six event types, matching the brief exactly:
`SelectionChanged`, `HoverChanged`, `CameraMoved`, `TimelineChanged`,
`SimulationPaused`, `SimulationResumed`. `EventBus` is a plain,
per-instance, synchronous pub/sub (a dict of callable lists) — no
framework, matching this codebase's existing bias against a dependency
for what a small class already does. `world.interaction.api`'s
module-level functions (`select`, `hover`, `dispatch`) publish to a
shared `EventBus` automatically; direct `SelectionManager`/`HoverManager`/
`CommandDispatcher` use does not publish on its own (the class boundary
is deliberately separate from the event-bus boundary — see each class's
docstring).

## 8. Search & Filters

`search(query)` does a case-insensitive substring match over room
ids/names, agent ids/refs, and current event ids/messages/kinds —
returning `Selection` tuples that pipe straight into
`SelectionManager.select()`. `filters.py` is six pure functions
(department, room type, agent state, simulation state, alerts, meetings)
over an already-fetched `WorldState`/`SimulationState` pair, mirroring
`relationship_resolver`'s style (pure, no I/O, no caching of their own).
"Room type" means the department-vs-circulation distinction
`world.frontend.rooms.room_type` already draws — there is no separate
"office type" enum in this codebase.

## 9. Command Dispatch

Nine read-only commands: `focus_room`, `follow_character`,
`center_camera`, `highlight_department`, `show_timeline`,
`jump_to_event`, `pause_simulation`, `resume_simulation`,
`set_simulation_speed`. Every successful command publishes the matching
`EventBus` event and, if a caller supplies an `InteractionHistory`,
records itself there. `CommandDispatcher.dispatch()` never raises for a
bad command or bad argument — it catches `ValueError`/`KeyError` and
returns `CommandResult(ok=False, detail=...)`, so a UI caller never needs
a try/except around every dispatch.

`set_simulation_speed` is the one command with no real backend effect:
`world.simulation.scheduler.SimulationScheduler.fps_target` is a fixed,
descriptive constant (not enforced), and Phase W7 has no polling loop
for a "speed" to govern — ticks only happen when something external
calls `step()`. Rather than inventing an effect that doesn't exist
anywhere in this codebase, this command stores the requested rate as a
plain preference value (`CommandResult.data["speedPreference"]`) with an
explicit `detail` string saying it doesn't change tick cadence. A future
Phase W10 UI with its own playback loop can read and interpret it.

## 10. Additive Change to Phase W7

`world.simulation.api.get_timeline()` was added — the only change to any
file outside `world/interaction/` and its own tests. It exposes
`SimulationEngine`'s already-built `Timeline` (previously unreachable
outside `world/simulation/`); no existing function's signature or
behavior changed.

## 11. Performance

Nothing in `world/interaction/` rebuilds the Phase W8 `SceneGraph` /
`RenderFrame` — the interaction layer reads `WorldState`/
`SimulationState` directly, the same inputs the renderer reads, rather
than reading renderer output. `SelectionManager` loads
`room_assets.json` once at construction (not per `select()` call),
matching `SimulationEngine._load_spatial`'s load-once pattern.
`InteractionHistory` and `EventBus`'s internal logs are both bounded
(`history_window` / no bound on `EventBus._log` — see its own module for
why: it's a debug/test log, not user-facing state, and is cleared
per-instance on every fresh `EventBus()`).

## 12. Tests

85 tests across 11 files in `world/tests/test_interaction_*.py`,
covering selection (valid/invalid ids for all six kinds), hover, the
inspector (merge correctness, history truncation, unknown-id handling),
timeline (seek, jump-to-event, unknown-event error), notifications
(category mapping, de-duplication), search, filters, command dispatch
(every one of the 9 commands, event publishing, unknown-command
handling), history (bounded window), the event bus (all six event
types), the tooltip formatter, the focus manager (including a real,
non-mocked room-anchor load), and one regression file exercising
`world.interaction.api`'s module-level functions against the real, live
`world.runtime`/`world.simulation` APIs end to end — no fakes.
