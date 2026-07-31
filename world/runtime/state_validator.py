"""state_validator — checks an already-built `WorldState` for internal
consistency. Returns a list of human-readable error strings (empty list
means valid); never raises for a *data* problem, only for a programming
error (e.g. being handed something that isn't a `WorldState`).

Checks performed, matching this phase's own Part G list:
- missing room: an agent or mission references a room_id that doesn't
  exist in `state.rooms`
- duplicate agent: the same agent_id appears more than once
- invalid mission: a mission's status isn't one of the values
  `missions.schema.json` (Phase W1) allows
- broken relationship: a room's `occupant_agent_ids` / `active_mission_ids`
  reference an agent/mission that isn't actually in `state.agents` /
  `state.missions`
- orphan notification: a notification whose id follows the
  `notif-from-<event_id>` convention (`SnapshotBuilder.build_notifications`,
  Phase W4) but whose referenced event isn't in `state.events`
"""

from world.runtime.models import WorldState

_VALID_MISSION_STATUSES = ("proposed", "active", "complete", "aborted")


def validate(state: WorldState) -> list[str]:
    errors: list[str] = []

    room_ids = {r.room_id for r in state.rooms}
    agent_ids = [a.agent_id for a in state.agents]
    agent_id_set = set(agent_ids)
    mission_ids = {m.mission_id for m in state.missions}
    event_ids = {e.event_id for e in state.events}

    # duplicate agent
    if len(agent_ids) != len(agent_id_set):
        dupes = {a for a in agent_ids if agent_ids.count(a) > 1}
        errors.append(f"Duplicate agent id(s): {sorted(dupes)}")

    # missing room (agent references a room that doesn't exist)
    for a in state.agents:
        if a.current_room_id not in room_ids:
            errors.append(
                f"Agent {a.agent_id!r} references missing room {a.current_room_id!r}"
            )

    # invalid mission
    for m in state.missions:
        if m.status not in _VALID_MISSION_STATUSES:
            errors.append(f"Mission {m.mission_id!r} has invalid status {m.status!r}")
        if m.district not in room_ids:
            errors.append(
                f"Mission {m.mission_id!r} references missing room {m.district!r}"
            )

    # broken relationship: room <-> agent / room <-> mission
    for r in state.rooms:
        for agent_id in r.occupant_agent_ids:
            if agent_id not in agent_id_set:
                errors.append(
                    f"Room {r.room_id!r} lists occupant {agent_id!r} not in state.agents"
                )
        for mission_id in r.active_mission_ids:
            if mission_id not in mission_ids:
                errors.append(
                    f"Room {r.room_id!r} lists mission {mission_id!r} not in state.missions"
                )

    # orphan notification
    for n in state.notifications:
        prefix = "notif-from-"
        if n.notification_id.startswith(prefix):
            referenced_event = n.notification_id[len(prefix):]
            if referenced_event not in event_ids:
                errors.append(
                    f"Notification {n.notification_id!r} references missing event "
                    f"{referenced_event!r}"
                )

    return errors


def is_valid(state: WorldState) -> bool:
    return validate(state) == []
