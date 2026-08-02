"""world.simulation.api — Phase W7, Part G. The only public surface most
callers should use, mirroring `world.runtime.api`'s shape for Phase W5.
Wraps one module-level `SimulationEngine` so repeated calls share the same
clock/timeline/movement state — construct your own `SimulationEngine`
directly instead if you need an isolated instance (as every test in
`world/tests/` does).
"""

from world.simulation.engine import SimulationEngine
from world.simulation.models import CharacterActivity, RoomActivityState, SimulationState
from world.simulation.timeline import Timeline

_engine = SimulationEngine()


def get_simulation_state() -> SimulationState:
    """Return the current `SimulationState`, stepping once if nothing has
    been simulated yet."""
    current = _engine.current_state()
    if current is None:
        return _engine.step()
    return current


def get_character_activity(agent_id: str) -> CharacterActivity | None:
    state = get_simulation_state()
    for c in state.characters:
        if c.agent_id == agent_id:
            return c
    return None


def get_room_activity(room_id: str) -> RoomActivityState | None:
    state = get_simulation_state()
    for r in state.rooms:
        if r.room_id == room_id:
            return r
    return None


def get_current_events() -> tuple:
    return get_simulation_state().events


def step() -> SimulationState:
    """Force the simulation forward by exactly one tick."""
    return _engine.step(force=True)


def pause() -> None:
    _engine.pause()


def resume() -> None:
    _engine.resume()


def reset() -> None:
    _engine.reset()


def get_timeline() -> Timeline:
    """Return the shared `SimulationEngine`'s `Timeline` — Phase W9,
    additive. Read-only from the caller's perspective in the sense that
    nothing here calls `Timeline.record()` (only `SimulationEngine.step()`
    does that); `Timeline.seek()`/`play()`/`pause()`/`resume()` remain
    available on the returned object for a Phase W9 timeline controller
    to move the *view* cursor without affecting simulation state itself.
    Was not exposed through this module in Phase W7 because nothing
    needed it yet; exposing it now needs no change to any existing
    function's signature or behavior."""
    return _engine.timeline
