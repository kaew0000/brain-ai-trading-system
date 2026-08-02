"""build_inspector_report — Inspector Panel.

Merges three read-only sources per the brief's field list:
- `world.runtime.api` (Phase W5): static-ish identity (name, room, status).
- `world.simulation.api` (Phase W7): current tick's behaviour/activity.
- `world.simulation.api.get_timeline()` (Phase W9 addition): retained
  history, filtered down to the ticks in which this target appeared, for
  `InspectorReport.historical_timeline`.
- `world.runtime.relationship_resolver` (Phase W5): department ownership,
  for `linked_runtime_data` on room/department selections.

A plain function (not a class) since, unlike `SelectionManager`/
`HoverManager`, there is no per-instance state to hold — every call is a
fresh, independent read. Never mutates anything it reads.
"""

from world.interaction.models import HistoryEntry, InspectorReport
from world.runtime import api as runtime_api
from world.runtime import relationship_resolver
from world.simulation import api as simulation_api

#: How many past ticks `historical_timeline` includes, most recent last.
#: Bounded so a long-lived Timeline (`history_window=500` by default in
#: `SimulationEngine`) doesn't dump hundreds of entries into one report.
DEFAULT_HISTORY_LIMIT = 20


def build_inspector_report(
    kind: str,
    target_id: str,
    history_limit: int = DEFAULT_HISTORY_LIMIT,
    get_world_state=runtime_api.get_world_state,
    get_simulation_state=simulation_api.get_simulation_state,
    get_timeline=simulation_api.get_timeline,
) -> InspectorReport:
    world_state = get_world_state()
    sim_state = get_simulation_state()

    if kind == "character":
        return _character_report(target_id, world_state, sim_state, get_timeline(), history_limit)
    if kind in ("room", "department"):
        return _room_report(target_id, world_state, sim_state, get_timeline(), history_limit)
    # furniture / decoration / event: identity-only, no runtime/simulation
    # record of their own to merge in — still a valid, complete report.
    return InspectorReport(id=target_id, name=target_id, kind=kind)


def _character_report(agent_id, world_state, sim_state, timeline, history_limit) -> InspectorReport:
    agent = next((a for a in world_state.agents if a.agent_id == agent_id), None)
    activity = next((c for c in sim_state.characters if c.agent_id == agent_id), None)
    room = None
    if agent is not None:
        room = next((r for r in world_state.rooms if r.room_id == agent.current_room_id), None)

    history = _character_history(agent_id, timeline, history_limit)

    return InspectorReport(
        id=agent_id,
        name=agent.agent_ref if agent else agent_id,
        kind="character",
        current_state=agent.status if agent else "",
        location=room.name if room else (agent.current_room_id if agent else ""),
        simulation_status=activity.behavior if activity else "",
        assigned_agent=agent.agent_ref if agent else "",
        current_activity=activity.behavior if activity else "",
        historical_timeline=history,
        linked_runtime_data={"isActive": agent.is_active if agent else False},
    )


def _room_report(room_id, world_state, sim_state, timeline, history_limit) -> InspectorReport:
    room = next((r for r in world_state.rooms if r.room_id == room_id), None)
    room_activity = next((r for r in sim_state.rooms if r.room_id == room_id), None)
    ownership = relationship_resolver.resolve_department_ownership()

    history = _room_history(room_id, timeline, history_limit)

    return InspectorReport(
        id=room_id,
        name=room.name if room else room_id,
        kind="room",
        current_state="active" if (room and room.is_active) else "inactive",
        location=room_id,
        simulation_status=room_activity.activity if room_activity else "",
        assigned_agent=", ".join(room.occupant_agent_ids) if room else "",
        current_activity=room_activity.activity if room_activity else "",
        historical_timeline=history,
        linked_runtime_data={
            "activeMissionIds": list(room.active_mission_ids) if room else [],
            "assignedAgentRefs": list(ownership.get(room_id, ())),
            "occupantCount": room_activity.occupant_count if room_activity else 0,
        },
    )


def _character_history(agent_id: str, timeline, limit: int) -> tuple[HistoryEntry, ...]:
    entries = []
    for state in _timeline_records(timeline):
        activity = next((c for c in state.characters if c.agent_id == agent_id), None)
        if activity is not None:
            entries.append(HistoryEntry(
                tick_number=state.tick.tick_number,
                behavior_or_activity=activity.behavior,
                room_id=activity.room_id,
            ))
    return tuple(entries[-limit:])


def _room_history(room_id: str, timeline, limit: int) -> tuple[HistoryEntry, ...]:
    entries = []
    for state in _timeline_records(timeline):
        activity = next((r for r in state.rooms if r.room_id == room_id), None)
        if activity is not None:
            entries.append(HistoryEntry(
                tick_number=state.tick.tick_number,
                behavior_or_activity=activity.activity,
                room_id=room_id,
            ))
    return tuple(entries[-limit:])


def _timeline_records(timeline):
    """`Timeline` deliberately exposes no public "give me every recorded
    state" accessor (only `current()`/`seek()`, one at a time) — its own
    docstring frames it as a play/pause/seek cursor, not an iterable log.
    Reading the private `_records` list here is a documented, intentional
    exception: `historical_timeline` genuinely needs every retained tick
    for one target, and duplicating `Timeline`'s storage in a second list
    (kept in sync on every `SimulationEngine.step()`) would be worse —
    two sources of truth for the same history instead of one."""
    return list(getattr(timeline, "_records", ()))
