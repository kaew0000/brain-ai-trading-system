# Live Office Simulation — Phase W7

Status: implemented. Pure backend, logical simulation state — no
renderer-specific code (nothing here imports `world.frontend`), no
trading/execution/AI-decision logic invented.

## 1. Architecture Report

Phase W7 sits directly on top of Phase W5's `WorldState` (via
`world.runtime.api.get_world_state()`) and reads Phase W6's asset-pipeline
data (`world/data/characters/spatial_placement.json` for spawn/working/
meeting/emergency positions and patrol routes) — it does not read
`world/data/runtime/*.json` directly, and it does not read
`world/frontend/` at all.

```
World State Provider (W5) ── WorldState (via world.runtime.api)
        │
        ▼
SimulationEngine.step()
        │   ├─ behavior.determine_behavior()       (Part B, per character)
        │   ├─ room_activity.determine_room_activity()  (Part C, per room)
        │   ├─ MovementController.step()           (Part D, per character)
        │   └─ event_descriptors.build_event_descriptors()  (Part E)
        ▼
SimulationState  (world/simulation/models.py — frozen, immutable)
        │
        ├──▶ Timeline.record()           (Part F — play/pause/resume/seek)
        ├──▶ statistics.compute_statistics()  (Part H)
        └──▶ world.simulation.api  (get_simulation_state / get_character_activity /
                                     get_room_activity / get_current_events /
                                     step / pause / resume / reset — Part G)
```

`SimulationScheduler` (Part A) mirrors Phase W5's `UpdateManager`: it
tracks whether the underlying `WorldState.sequence` has changed, for
bookkeeping — but unlike W5, a simulation tick still needs to run every
call regardless (characters keep walking even when nothing in the trading
engine changed), so `SimulationEngine.step()` always advances the clock and
movement; the scheduler's role here is informational (exposed via
`fps_target`, used by `statistics`), not gating.

## 2. Character Behaviour Model (Part B)

`world/simulation/behavior.py::determine_behavior` — one of 7 labels
(`idle`, `walking`, `working`, `meeting`, `emergency`, `celebration`,
`resting`), checked in a fixed, documented precedence order (first match
wins): **emergency > meeting > celebration > working > resting > walking >
idle**. Every branch is derived only from `WorldState` fields (`AgentState.
status`/`is_active`, room-district event severity, `relationship_resolver.
resolve_active_meetings`) — nothing here invents a trading event that
`WorldState` doesn't already carry. A final `assert` checks the result
against `CHARACTER_BEHAVIORS` before returning, so this is a real runtime
guarantee, not just documentation.

`resting` is the one deliberately narrow heuristic: "home room is
`recovery-center` and not currently active" — there's no dedicated
"resting" runtime signal (same category of documented heuristic as W5's
`resolve_active_meetings`).

## 3. Room Activity Model (Part C)

`world/simulation/room_activity.py::determine_room_activity` — one of 6
labels (`quiet`, `busy`, `meeting`, `alert`, `critical`, `celebration`),
precedence **critical > alert > meeting > celebration > busy > quiet**.
Same discipline: derived only from `WorldState`, same runtime-asserted
guarantee against `ROOM_ACTIVITIES`.

## 4. Movement System (Part D)

`world/simulation/movement.py`:
- `NavigationGraph` — Dijkstra shortest path over `world/data/navigation/
  graph.json`'s real `distance` weights (Phase W2). Read-only.
- `MovementController` — one `MovementPlan` per agent (current position,
  current room, pending target, room waypoints). `step()` moves a fixed
  logical distance per tick toward the target, entering rooms one at a
  time along the shortest path when the target is in a different room.

Room transitions, patrol routes, and meeting destinations are all the
same mechanism: `set_destination(agent_id, position, room_id)` — the
*source* of that destination differs (patrol route cycling vs. a static
`meetingPosition` from `spatial_placement.json`), but the movement math
doesn't care which.

**Real finding, documented rather than hidden:** `world/data/navigation/
graph.json`'s node set is the 14 departments plus `elevator-floor-1/2/3` —
it has no `lobby` or `hallway` nodes at all, even though the Phase W6
asset pipeline populated furniture into rooms literally named `lobby` and
`hallway` (generic `CirculationType` ids). No real character's home room
is `lobby`/`hallway` (`world/data/characters/placement.json` only uses
real department ids), so this doesn't affect movement for any of the 16
real characters — but it's a real naming gap between Phase W2 and Phase W6
worth fixing before anything ever needs to route a character through the
lobby.

## 5. Event Animation Model (Part E)

`world/simulation/event_descriptors.py` — metadata-only `EventDescriptor`
records (`event_id`, `kind`, `room_id`, `agent_id`, `timestamp`, `message`)
built from every `WorldState.events` and `WorldState.notifications` entry.
`classify_event_kind` maps the trading engine's free-form `event_type`
string (Phase W4 doesn't constrain it) down to one of six fixed kinds
(`trade_opened`, `trade_closed`, `risk_alert`, `portfolio_growth`,
`system_recovery`, `notification`) via documented keyword matching, with
`"notification"` as the catch-all rather than silently dropping anything
unrecognized.

## 6. Timeline Design (Part F)

`world/simulation/timeline.py::Timeline` — an in-memory, optionally
rolling-window (`history_window`) list of recorded `SimulationState`s plus
a cursor:
- `record()` — append; cursor follows if playing, stays put if paused.
- `play()` — jump to the beginning of retained history.
- `pause()` / `resume()` — freeze/continue from the current cursor.
- `seek(tick_number)` — jump to a specific tick if still retained
  (implicitly pauses); returns `None` without moving the cursor if that
  tick has aged out of the window.

No video, no rendering — `SimulationState.to_dict()` is the only
"playback" output, for something else to render later.

## 7. Simulation API (Part G)

`world/simulation/api.py` exposes exactly the 8 functions specified:
`get_simulation_state()`, `get_character_activity(agent_id)`,
`get_room_activity(room_id)`, `get_current_events()`, `step()`, `pause()`,
`resume()`, `reset()`. Deliberately does **not** add a 9th "get statistics"
function here (unlike Phase W5's `api.py`, whose own Part H explicitly
listed one) — `world.simulation.statistics.compute_statistics` is called
directly against an engine instance instead, since this phase's own Part G
list doesn't include a stats getter.

## 8. Statistics (Part H)

`world/simulation/statistics.py::compute_statistics` reports (all *this
tick*, not cumulative): active/idle character counts and idle percentage,
active room count, movement count (characters currently `walking`),
meeting count (characters currently `meeting`), alert percentage (rooms
`alert`/`critical`), timeline length, and the logical `simulation_fps_
target` (a design constant, not an enforced or measured real-time rate).

## 9. Performance (Part K)

`world/scripts/benchmark_simulation.py` — real, synthetic-agent-count
benchmark (the real office only has 16 characters, so 10/50/100/500
"simulated agents" means synthetic `AgentState`/`RoomState` fixtures, the
same approach Phase W5's benchmark took for synthetic runtime files), 20
steps per scale:

| agents | total (s) | avg step (ms) | avg/agent (μs) | peak mem (KB) |
|---|---|---|---|---|
| 10 | 0.0077 | 0.386 | 38.57 | 108.7 |
| 50 | 0.0250 | 1.248 | 24.96 | 300.5 |
| 100 | 0.0429 | 2.144 | 21.44 | 548.8 |
| 500 | 0.2665 | 13.323 | 26.65 | 2481.6 |

Per-step time scales roughly linearly with agent count, as expected (each
character's behavior/movement/room-activity derivation is independent
work). Per-agent cost stays in a narrow ~21–39μs band across two orders of
magnitude — no quadratic blowup. Peak memory scales sub-linearly relative
to the 50x agent-count increase from 10→500 (108.7KB→2481.6KB, ~23x), since
`Timeline`'s `history_window` bounds how many `SimulationState` snapshots
are retained regardless of how many characters each one contains.

## 10. Future Interactive Layer (W8+)

This phase's `SimulationState` (and `Timeline`'s recorded history) is
exactly what a future interactive/renderer layer needs to actually draw
and let someone click on: `CharacterActivity.position` +`.behavior`,
`RoomActivityState.activity`, and `EventDescriptor`s ready to animate.
Wiring that up — plus the still-outstanding Phase W6 renderer-integration
half (picking a concrete engine, implementing the Phase W3
`WorldStateProvider` ABC) — remains future work; nothing in this phase
assumes or requires it to exist yet.
