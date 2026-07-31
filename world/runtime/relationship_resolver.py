"""RelationshipResolver — pure functions over an already-built `WorldState`
(plus the static Phase W1 district canon for department ownership). No
renderer logic, no I/O: every function here takes data in, returns data
out.

Two related-but-distinct concepts are kept separate on purpose:
- "room occupants" / "agent locations" — *dynamic*, from the `WorldState`
  itself (where an agent actually is right now).
- "department ownership" — *static*, from `world/districts/definitions/`
  (`assignedAgents`, Phase W1) — which agents a department is defined to
  belong to, regardless of where anyone currently is.
"""

import json
import os

from world.runtime.models import WorldState

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_THIS_DIR)
DISTRICT_DEFS_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")


def resolve_agent_locations(state: WorldState) -> dict[str, str]:
    """agent_id -> current_room_id."""
    return {a.agent_id: a.current_room_id for a in state.agents}


def resolve_room_occupants(state: WorldState) -> dict[str, tuple[str, ...]]:
    """room_id -> tuple of agent ids currently in it (already computed by
    `StateBuilder`, exposed here for symmetry with the other resolvers and
    so callers don't need to reach into `RoomState` directly)."""
    return {r.room_id: r.occupant_agent_ids for r in state.rooms}


def resolve_mission_owners(state: WorldState) -> dict[str, tuple[str, ...]]:
    """mission_id -> tuple of agent ids currently occupying that mission's
    department. A mission with no one currently in its department maps to
    an empty tuple, not an error — missions can exist before anyone is
    dynamically placed there."""
    occupants_by_room = resolve_room_occupants(state)
    return {
        m.mission_id: occupants_by_room.get(m.district, ())
        for m in state.missions
    }


def resolve_active_meetings(state: WorldState) -> tuple[str, ...]:
    """room_ids currently treated as "in an active meeting": at least two
    agents currently occupying the room AND at least one active mission
    assigned to that room's department. This is a deliberately simple,
    documented heuristic — there is no dedicated "meeting" runtime source
    yet, so this infers it from what W4 already provides rather than
    inventing new snapshot data."""
    meetings = []
    for room in state.rooms:
        if len(room.occupant_agent_ids) >= 2 and len(room.active_mission_ids) >= 1:
            meetings.append(room.room_id)
    return tuple(meetings)


def resolve_department_ownership(
    district_defs_dir: str = DISTRICT_DEFS_DIR,
) -> dict[str, tuple[str, ...]]:
    """Static room_id -> tuple of agentRefs the department is *defined* to
    belong to (Phase W1 `assignedAgents`), independent of runtime state."""
    ownership: dict[str, tuple[str, ...]] = {}
    if not os.path.isdir(district_defs_dir):
        return ownership
    for fname in sorted(os.listdir(district_defs_dir)):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(district_defs_dir, fname)) as f:
            d = json.load(f)
        ownership[d["id"]] = tuple(d.get("assignedAgents", []))
    return ownership
