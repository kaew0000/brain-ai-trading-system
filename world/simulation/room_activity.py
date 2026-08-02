"""Room activity — Part C. Derived only from `WorldState` (Phase W5), same
discipline as `behavior.py`. Precedence (first match wins), documented for
the same reason: critical > alert > meeting > celebration > busy > quiet.

1. **critical** — a `critical`-severity event or notification against the
   room this tick.
2. **alert** — a `warning`-severity event against the room this tick.
3. **meeting** — the room is in `relationship_resolver.
   resolve_active_meetings`.
4. **celebration** — a `success`-severity, growth-shaped event against the
   room (same shape `behavior._is_growth_event` checks, kept as its own
   copy here rather than a cross-module import, since room-level and
   character-level growth detection are allowed to diverge later without
   entangling the two modules).
5. **busy** — at least one occupant.
6. **quiet** — none of the above.
"""

from world.runtime.models import RoomState, WorldState
from world.runtime.relationship_resolver import resolve_active_meetings
from world.simulation.models import ROOM_ACTIVITIES

_GROWTH_EVENT_TYPES = frozenset({"portfolio_growth", "trade_closed"})


def determine_room_activity(room: RoomState, state: WorldState) -> str:
    """Return one of `ROOM_ACTIVITIES` for the given room. The final
    `assert` is a real runtime guarantee, not documentation."""
    room_events = [e for e in state.events if e.district == room.room_id]

    if any(e.severity == "critical" for e in room_events):
        activity = "critical"
    elif any(e.severity == "warning" for e in room_events):
        activity = "alert"
    elif room.room_id in resolve_active_meetings(state):
        activity = "meeting"
    elif any(e.severity == "success" and e.event_type in _GROWTH_EVENT_TYPES for e in room_events):
        activity = "celebration"
    elif len(room.occupant_agent_ids) > 0:
        activity = "busy"
    else:
        activity = "quiet"

    assert activity in ROOM_ACTIVITIES, f"invalid room activity label: {activity!r}"
    return activity
