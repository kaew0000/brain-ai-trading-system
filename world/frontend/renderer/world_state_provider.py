"""RenderWorldStateProvider — Phase W8.

Implements `world.frontend.interfaces.world_state.WorldStateProvider`
— the one Phase W3 ABC that, per `world/docs/roadmap.md` item 10 and
`world/runtime/world_state_provider.py`'s own docstring, was
explicitly left unimplemented until "Renderer Integration." This is
that implementation.

Projects two backend snapshots down to one flattened
`world.frontend.renderer.world_state.WorldState`:

- `world.runtime.api.get_world_state()` (Phase W5) — static-ish
  per-room identity (`name`, `is_active`, mission ids) and per-agent
  identity (`agent_ref`, `current_room_id`).
- `world.simulation.api.get_simulation_state()` (Phase W7) — the
  per-tick behaviour/activity/position data that actually changes
  frame to frame.

Deliberate documented deviation from the Phase W3 docstring on
`world.frontend.renderer.world_state.WorldState.character_states`
("character_id -> one of ... STANDARD_ANIMATION_STATES"): that
comment predates Phase W7, which produces seven behaviour labels
(`world.simulation.models.CHARACTER_BEHAVIORS`), not five. This
provider stores the *raw* seven-label behaviour in
`character_states`, unmapped — `WorldState` is meant to be a truthful
snapshot of what the simulation knows, not something that has already
silently dropped information a future consumer (e.g. an interaction
layer, Phase W9) might need. The five-state animation fallback lives
in `sprite_mapper.SpriteMapper`, one layer further down the pipeline,
where it belongs (it's a *sprite selection* concern, not a *world
state* concern). See `render_config.BEHAVIOR_TO_ANIMATION_STATE`.
"""

from typing import Callable

from world.frontend.interfaces.world_state import WorldStateProvider
from world.frontend.renderer.world_state import WorldState
from world.runtime import api as runtime_api
from world.runtime.models import WorldState as RuntimeWorldState
from world.simulation import api as simulation_api
from world.simulation.models import SimulationState


class RenderWorldStateProvider(WorldStateProvider):
    """Concrete `WorldStateProvider`. Read-only: never calls anything
    on `world.runtime` or `world.simulation` that could mutate engine
    or simulation state (`get_world_state` / `get_simulation_state`
    only — never `refresh_world`, `step`, `pause`, `resume`, `reset`).

    `get_runtime_state`/`get_simulation_state` are injectable (default
    to the real module-level Phase W5/W7 APIs) so tests can supply
    fixed snapshots instead of depending on live simulation ticks.
    """

    def __init__(
        self,
        get_runtime_state: Callable[[], RuntimeWorldState] = runtime_api.get_world_state,
        get_simulation_state: Callable[[], SimulationState] = simulation_api.get_simulation_state,
    ) -> None:
        self._get_runtime_state = get_runtime_state
        self._get_simulation_state = get_simulation_state

    def get_current_state(self) -> WorldState:
        runtime_state = self._get_runtime_state()
        sim_state = self._get_simulation_state()

        room_names = {room.room_id: room.name for room in runtime_state.rooms}
        room_active = {room.room_id: room.is_active for room in runtime_state.rooms}
        room_missions = {room.room_id: room.active_mission_ids for room in runtime_state.rooms}

        district_status = {}
        for room_activity in sim_state.rooms:
            room_id = room_activity.room_id
            district_status[room_id] = {
                "name": room_names.get(room_id, room_id),
                "activity": room_activity.activity,
                "occupantCount": room_activity.occupant_count,
                "isActive": room_active.get(room_id, False),
                "activeMissionIds": list(room_missions.get(room_id, ())),
            }

        character_states = {c.agent_id: c.behavior for c in sim_state.characters}
        character_positions = {
            c.agent_id: {"room_id": c.room_id, "x": c.position.x, "y": c.position.y}
            for c in sim_state.characters
        }
        recent_events = tuple(e.to_dict() for e in sim_state.events)

        return WorldState(
            district_status=district_status,
            character_states=character_states,
            character_positions=character_positions,
            recent_events=recent_events,
            sequence=sim_state.tick.tick_number,
        )
