"""world.runtime.api — Phase W5, Part H. The only public surface most
callers should use. Read-only: nothing here can mutate engine or Track A
state, and nothing here writes to `world/data/runtime/` (that remains
exclusively `RuntimeManager`'s job, Phase W4).

Wraps one module-level `WorldStateProvider` so repeated calls share the
same cache (and therefore the same change-detection/hit-ratio behavior) —
construct your own `WorldStateProvider` directly instead if you need an
isolated instance (as every test in `world/tests/` does)."""

from world.runtime.models import AgentState, RoomState, WorldState
from world.runtime.statistics import WorldStatistics, compute_statistics
from world.runtime.world_state_provider import WorldStateProvider

_provider = WorldStateProvider()


def get_world_state() -> WorldState:
    """Return the current `WorldState`, rebuilding only if the underlying
    Phase W4 runtime files have changed since the last call."""
    return _provider.get_current_state()


def get_room_state(room_id: str) -> RoomState | None:
    """Return the named room's state, or `None` if `room_id` isn't a real
    department/circulation id."""
    state = _provider.get_current_state()
    for room in state.rooms:
        if room.room_id == room_id:
            return room
    return None


def get_agent_state(agent_id: str) -> AgentState | None:
    """Return the named agent's state, or `None` if `agent_id` isn't a
    real character id."""
    state = _provider.get_current_state()
    for agent in state.agents:
        if agent.agent_id == agent_id:
            return agent
    return None


def refresh_world() -> WorldState:
    """Force a rebuild regardless of whether the runtime files changed."""
    return _provider.refresh()


def get_world_statistics() -> WorldStatistics:
    state = _provider.get_current_state()
    return compute_statistics(state, _provider.update_manager.cache)
