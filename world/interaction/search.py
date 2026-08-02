"""search — Search section (Agent, Room, Department, Event, ID).

Plain substring match (case-insensitive) over real identity fields from
`world.runtime.api` (rooms, agents) and `world.simulation.api` (current
events) — no fuzzy matching, no external search index, matching this
codebase's existing preference for the simplest thing that actually
works over `world/data/*`-sized data (a few dozen rooms/agents, not
thousands).

Returns a flat list of `world.interaction.models.Selection` — same shape
`SelectionManager.select()` produces, so a caller can pipe a search
result straight into `SelectionManager.select(result.kind,
result.target_id)` without a translation step.
"""

from world.interaction.models import Selection
from world.runtime import api as runtime_api
from world.simulation import api as simulation_api


def search(
    query: str,
    get_world_state=runtime_api.get_world_state,
    get_current_events=simulation_api.get_current_events,
) -> tuple[Selection, ...]:
    """Search rooms, agents, and current events by id or name, plus a
    direct id lookup (an exact `target_id`/`event_id` match against any
    kind, useful for "search by ID" per the brief). Case-insensitive
    substring match on the free-text fields."""
    needle = query.strip().lower()
    if not needle:
        return ()

    results: list[Selection] = []
    state = get_world_state()

    for room in state.rooms:
        if needle in room.room_id.lower() or needle in room.name.lower():
            results.append(Selection(kind="room", target_id=room.room_id))

    for agent in state.agents:
        if needle in agent.agent_id.lower() or needle in agent.agent_ref.lower():
            results.append(Selection(kind="character", target_id=agent.agent_id))

    for event in get_current_events():
        if needle in event.event_id.lower() or needle in event.message.lower() or needle in event.kind.lower():
            results.append(Selection(kind="event", target_id=event.event_id))

    return tuple(results)
