"""Character behaviour — Part B. Every transition is derived only from
`world.runtime.models.WorldState` (Phase W5) — no trading events are
invented here; if `WorldState` doesn't say it happened, this module
doesn't decide it happened either.

Precedence (checked in order, first match wins) — documented here since
the mapping from "several true facts about an agent" to "one behaviour
label" necessarily picks a priority:

1. **emergency** — the agent's room has a `critical`-severity event or
   notification against it this tick.
2. **meeting** — the agent is in a room `relationship_resolver.
   resolve_active_meetings` flags as an active meeting.
3. **celebration** — the agent's room has a `success`-severity event
   whose type is portfolio-growth-shaped (see `_is_growth_event`).
4. **working** — `AgentState.status == "working"` (Phase W5's own
   active/idle flag).
5. **resting** — the agent's home room is `recovery-center` and it is not
   active (a deliberately narrow, documented heuristic — there is no
   dedicated "resting" runtime source).
6. **walking** — the agent has an in-progress movement plan
   (`MovementController.has_arrived` is `False`).
7. **idle** — none of the above.
"""

from world.runtime.models import WorldState
from world.runtime.relationship_resolver import resolve_active_meetings
from world.simulation.models import CHARACTER_BEHAVIORS
from world.simulation.movement import MovementController

_GROWTH_EVENT_TYPES = frozenset({"portfolio_growth", "trade_closed"})


def _room_has_critical_signal(state: WorldState, room_id: str) -> bool:
    for e in state.events:
        if e.district == room_id and e.severity == "critical":
            return True
    return False


def _room_has_growth_signal(state: WorldState, room_id: str) -> bool:
    for e in state.events:
        if e.district == room_id and e.severity == "success" and e.event_type in _GROWTH_EVENT_TYPES:
            return True
    return False


def determine_behavior(
    agent_id: str,
    state: WorldState,
    movement: MovementController,
) -> str:
    """Return one of `CHARACTER_BEHAVIORS` for the named agent, given the
    current `WorldState` and movement controller. The final `assert`
    below is a real runtime guarantee, not documentation: every branch is
    checked against the same declared set of valid labels before this
    function can return."""
    agent = next((a for a in state.agents if a.agent_id == agent_id), None)

    if agent is None:
        behavior = "idle"
    elif _room_has_critical_signal(state, agent.current_room_id):
        behavior = "emergency"
    elif agent.current_room_id in resolve_active_meetings(state):
        behavior = "meeting"
    elif _room_has_growth_signal(state, agent.current_room_id):
        behavior = "celebration"
    elif agent.status == "working":
        behavior = "working"
    elif agent.current_room_id == "recovery-center" and not agent.is_active:
        behavior = "resting"
    elif not movement.has_arrived(agent_id):
        behavior = "walking"
    else:
        behavior = "idle"

    assert behavior in CHARACTER_BEHAVIORS, f"invalid behavior label: {behavior!r}"
    return behavior
