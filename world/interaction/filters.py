"""filters — Filters section (Department, Room type, Agent state,
Simulation state, Alerts, Meetings).

Every function here is a pure filter over a `world.runtime.models.
WorldState` + `world.simulation.models.SimulationState` pair the caller
already fetched — mirrors `world.runtime.relationship_resolver`'s style
(pure functions over already-built state, no I/O, no caching of their
own) rather than re-fetching state per filter call.

"Room type" per the brief means the department-vs-circulation distinction
`world.frontend.rooms.room_type` already draws (see that module's
docstring for why there's no separate "office type" enum in this
codebase) — `filter_by_room_type("department")` keeps rooms whose id is a
real department id; `filter_by_room_type("circulation")` keeps everything
else the current `WorldState` knows about.
"""

from world.frontend.rooms.room_type import load_department_ids
from world.runtime import relationship_resolver
from world.runtime.models import RoomState, WorldState
from world.simulation.models import SimulationState


def filter_rooms_by_department(state: WorldState, room_ids: tuple[str, ...]) -> tuple[RoomState, ...]:
    wanted = set(room_ids)
    return tuple(r for r in state.rooms if r.room_id in wanted)


def filter_by_room_type(state: WorldState, room_type: str) -> tuple[RoomState, ...]:
    if room_type not in ("department", "circulation"):
        raise ValueError("room_type must be 'department' or 'circulation'")
    department_ids = set(load_department_ids())
    if room_type == "department":
        return tuple(r for r in state.rooms if r.room_id in department_ids)
    return tuple(r for r in state.rooms if r.room_id not in department_ids)


def filter_agents_by_state(state: WorldState, status: str) -> tuple:
    return tuple(a for a in state.agents if a.status == status)


def filter_rooms_by_simulation_state(sim_state: SimulationState, activity: str) -> tuple:
    return tuple(r for r in sim_state.rooms if r.activity == activity)


def filter_alerts(sim_state: SimulationState) -> tuple:
    """Rooms currently at `alert` or `critical` activity — the same two
    values `world.simulation.models.ROOM_ACTIVITIES` reserves for
    alert-shaped states."""
    return tuple(r for r in sim_state.rooms if r.activity in ("alert", "critical"))


def filter_meetings(state: WorldState) -> tuple[str, ...]:
    """Room ids currently in an active meeting, per
    `world.runtime.relationship_resolver.resolve_active_meetings` (Phase
    W5's own documented heuristic) — reused rather than re-derived here."""
    return relationship_resolver.resolve_active_meetings(state)
