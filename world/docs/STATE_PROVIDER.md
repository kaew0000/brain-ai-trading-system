# World State Provider — Phase W5

Status: implemented. Pure backend, in-memory state only — no renderer
(React/PixiJS/Phaser/Godot/Unity) is touched or chosen. That is Phase W6.

## 1. Architecture Report

Phase W4 (`world/adapter/`, `world/readers/`, `world/watchers/`,
`world/runtime/runtime_manager.py`) already turns raw engine-adjacent
sources into six flat JSON files under `world/data/runtime/` (`world.json`,
`events.json`, `missions.json`, `portfolio.json`, `telemetry.json`,
`notifications.json`), written only when their content actually changes.

Phase W5 adds one more read-only layer on top: it reads those six files
(never writing to them — that stays exclusively `RuntimeManager`'s job),
merges them with the static Phase W1/W2 canon (which departments, which
characters, whose desk is where), and produces one immutable, in-memory
`WorldState` — the first point in the whole pipeline where "what is the
world doing right now" exists as one coherent, validated object rather than
six independent files.

```
world/adapter, world/readers, world/watchers, world/runtime/runtime_manager.py   (Phase W4 — unchanged)
        │  writes only, hash-gated
        ▼
world/data/runtime/*.json  (6 flat files)
        │  read only
        ▼
StateBuilder.build()  ── merges with static world/districts, world/characters, world/data/characters/placement.json canon
        │
        ▼
WorldState  (world/runtime/models.py — frozen, immutable, serializable)
        │
        ├──▶ state_validator.validate()        (integrity checks)
        ├──▶ relationship_resolver.resolve_*()  (occupancy, meetings, ownership)
        ├──▶ statistics.compute_statistics()    (aggregate numbers)
        └──▶ world.runtime.api  (get_world_state / get_room_state / get_agent_state /
                                  refresh_world / get_world_statistics — read only)
```

`UpdateManager` sits between `StateBuilder` and everything above it:
it hashes the six runtime files and only calls `StateBuilder.build()` again
when that hash has actually changed, returning the same cached `WorldState`
object otherwise (see §3).

## 2. World State Design

`world/runtime/models.py` defines eight frozen dataclasses:
`WorldState`, `RoomState`, `AgentState`, `MissionState`, `PortfolioState`,
`NotificationState` (all requested by name), plus `EventState` and
`TelemetryState` — added because Part A's own merge responsibilities name
`telemetry` and `events` explicitly, and leaving those as untyped dicts
would mean only some runtime sources got the validation/serialization
guarantees the rest do.

Every collection field is a `tuple`, not a `list` — combined with
`frozen=True`, a `WorldState` (and everything inside it) is fully
immutable once built. Every model has a `to_dict()` producing camelCase
keys, matching every existing schema in this repo (`missions.schema.json`,
`districts.schema.json`, etc.) rather than raw Python field names.

`RoomState.occupant_agent_ids` / `active_mission_ids` and
`AgentState.current_room_id` are computed once, inside `StateBuilder`, from:
- **static** home room: `world/data/characters/placement.json` (Phase W2)
- **dynamic** activity: `activeAgents` / `activeDistricts` in the Phase W4
  `world.json` runtime snapshot

An agent not currently flagged active simply stays at its static home room
with `status="idle"`; one that is active gets `status="working"`. There is
no separate "meeting room" runtime source, so meeting detection is a
documented heuristic in `relationship_resolver.resolve_active_meetings`
(see §4), not a new field on `RoomState`.

## 3. Cache Design

`StateCache` (`world/runtime/state_cache.py`) holds exactly one `WorldState`
plus:
- an optional **TTL** (`ttl_seconds`) — `None` means never expire on time
  alone
- a **content hash** of the six runtime files at the time of the last build
- **hit/miss counters** and **refresh count**
- **last rebuild duration** and enough timestamps to compute
  **update frequency** (refreshes per second across the cache's lifetime)

`UpdateManager` (`world/runtime/update_manager.py`) is the only thing that
decides *whether* to rebuild: it hashes the six runtime files with
SHA-256 on every `get_state()` call and only calls `StateBuilder.build()`
if that hash differs from the cache's stored hash (or `force=True` is
passed). No polling loop exists anywhere in `world/runtime/` — `get_state()`
only checks when something calls it, matching this phase's own instruction.

## 4. Relationship Graph

`world/runtime/relationship_resolver.py` exposes five pure functions,
deliberately split into **dynamic** (from the just-built `WorldState`) vs.
**static** (from Phase W1 canon, independent of runtime state):

| Function | Dynamic/Static | What it answers |
|---|---|---|
| `resolve_agent_locations` | dynamic | Where is each agent right now? |
| `resolve_room_occupants` | dynamic | Who is in each room right now? |
| `resolve_mission_owners` | dynamic | Which agents currently occupy a mission's department? |
| `resolve_active_meetings` | dynamic | Which rooms have ≥2 occupants *and* ≥1 active mission? (documented heuristic — no dedicated "meeting" runtime source exists yet) |
| `resolve_department_ownership` | static | Which agents is a department *defined* to belong to (`assignedAgents`, Phase W1), regardless of current occupancy? |

## 5. Validation

`world/runtime/state_validator.py::validate(state)` returns a list of
human-readable error strings (empty = valid), checking exactly the five
things Part G named: missing room, duplicate agent, invalid mission,
broken relationship, orphan notification. It never raises for a data
problem — only a real built `WorldState` with bad data returns non-empty.

## 6. Runtime API (Part H)

`world/runtime/api.py` exposes exactly five functions, per spec:
`get_world_state()`, `get_room_state(room_id)`, `get_agent_state(agent_id)`,
`refresh_world()`, `get_world_statistics()`. All read-only; none can mutate
engine or Track A state, and none writes to `world/data/runtime/`.

## 7. Statistics (Part I)

`world/runtime/statistics.py::compute_statistics` reports: active/inactive
room counts, active/inactive agent counts, total missions, total
notifications, portfolio position count + symbol list, cache hit ratio,
refresh count, last rebuild duration, and update frequency (refreshes/sec).

## 8. Performance (Part L)

`world/scripts/benchmark_runtime.py` — run for real (never fabricated),
against a temporary directory (never touches `world/data/runtime/`),
10/100/1,000/10,000 sequential updates each forcing a real rebuild
(`world.json`'s timestamp changes every iteration), followed by a
same-size read-only pass to measure the cache-hit case:

| N | rebuild total (s) | rebuild avg (ms) | cached avg (ms) | peak mem, rebuild pass (KB) | hit ratio |
|---|---|---|---|---|---|
| 10 | 0.0509 | 5.09 | 0.073 | 74.3 | 0.950 |
| 100 | 0.3044 | 3.04 | 0.085 | 114.9 | 0.995 |
| 1,000 | 2.8699 | 2.87 | 0.068 | 260.3 | 1.000 |
| 10,000 | 27.5733 | 2.76 | 0.071 | 459.7 | 1.000 |

Cache hits are consistently ~40–70× faster than a rebuild (sub-0.1ms vs.
2.7–5ms), and peak memory grows sub-linearly with N (rebuilds don't
accumulate — each `WorldState` replaces the last, and the old one becomes
garbage once nothing references it).

**Honest finding, not hidden:** rebuild time does *not* stay flat as N
grows — it's dominated by `StateBuilder` re-reading the static canon (16
character definitions + 14 district definitions + `placement.json`) from
disk on *every single* `build()` call, even though none of that ever
changes at runtime. This benchmark surfaced that rather than a synthetic
one that might not have. It's a legitimate optimization for a future phase
(cache the static canon separately, keyed on its own much-less-frequently-
changing hash) — flagged in §9/Risks rather than fixed here, since Part B's
own instruction is "resolve missing data, apply defaults," not "optimize
static reads," and this phase's tests already pass the informal <5s/100-
updates regression guard comfortably.

## 9. Future Renderer Integration (Phase W6)

This phase's `WorldStateProvider` (`world/runtime/world_state_provider.py`)
is intentionally **not** a subclass of
`world.frontend.interfaces.world_state.WorldStateProvider` (the Phase W3
ABC, which returns the flattened renderer-facing
`world.frontend.renderer.world_state.WorldState`). Phase W6
("Renderer Integration") is expected to:

1. Pick a concrete renderer engine (React Canvas, PixiJS, Phaser, Godot, or
   Unity — all equally supported by the Phase W3 interfaces).
2. Implement the Phase W3 ABC by wrapping this phase's
   `world.runtime.world_state_provider.WorldStateProvider`, projecting its
   richer `world.runtime.models.WorldState` down to the simpler
   `district_status` / `character_states` / `character_positions` /
   `recent_events` / `sequence` shape the ABC's callers expect.
3. Fold in the orphaned Phase W6 Asset Pipeline work (furniture/decoration/
   character-sprite metadata, built but never merged — see git history for
   `feature/world-phase-w6-asset-pipeline`) as part of actually rendering
   something with those assets, per Krush's decision to defer that
   integration until a renderer exists to integrate it with.
