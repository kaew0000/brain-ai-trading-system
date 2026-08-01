"""SimulationEngine — Part A. The one class that ties together
`SimulationClock`, `SimulationScheduler`, `MovementController`,
`behavior.determine_behavior`, `room_activity.determine_room_activity`,
`event_descriptors.build_event_descriptors`, and `Timeline` into one
`step()` call producing one `SimulationState`.

Reads `world.runtime.api.get_world_state()` (Phase W5) for runtime data,
and `world/data/characters/spatial_placement.json` (Phase W2/W6) once at
construction for each character's static target positions and patrol
route — never re-read per tick, learning from the Phase W5 benchmark
finding that re-reading static canon on every rebuild is wasted work (see
`world/docs/STATE_PROVIDER.md` §8).

No renderer-specific code: nothing here imports `world.frontend`.
"""

import json
import os

from world.runtime import api as runtime_api
from world.runtime.models import WorldState
from world.runtime.relationship_resolver import resolve_active_meetings
from world.simulation.behavior import determine_behavior
from world.simulation.clock import SimulationClock
from world.simulation.event_descriptors import build_event_descriptors
from world.simulation.models import (
    CharacterActivity,
    Position,
    RoomActivityState,
    SimulationState,
    SimulationTick,
)
from world.simulation.movement import MovementController
from world.simulation.room_activity import determine_room_activity
from world.simulation.scheduler import SimulationScheduler
from world.simulation.timeline import Timeline

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_THIS_DIR)
DEFAULT_SPATIAL_PATH = os.path.join(WORLD_ROOT, "data", "characters", "spatial_placement.json")


def _load_spatial(spatial_path: str) -> dict[str, dict]:
    if not os.path.isfile(spatial_path):
        return {}
    with open(spatial_path) as f:
        data = json.load(f)
    return {row["characterId"]: row for row in data}


class SimulationEngine:
    def __init__(
        self,
        spatial_path: str = DEFAULT_SPATIAL_PATH,
        history_window: int | None = 500,
        get_world_state=runtime_api.get_world_state,
    ) -> None:
        self._spatial = _load_spatial(spatial_path)
        self._get_world_state = get_world_state
        self._clock = SimulationClock()
        self._scheduler = SimulationScheduler()
        self._movement = MovementController()
        self._timeline = Timeline(history_window=history_window)
        self._patrol_index: dict[str, int] = {}
        self._running = True
        self._placed = False

    # -- setup -------------------------------------------------------

    def _ensure_placed(self, state: WorldState) -> None:
        """Place every real character at its spawn position on the very
        first step — after this, positions only ever move via
        `MovementController.step()`."""
        if self._placed:
            return
        for agent in state.agents:
            row = self._spatial.get(agent.agent_id)
            if row is None:
                self._movement.place(agent.agent_id, Position(0.0, 0.0), agent.current_room_id)
                continue
            spawn = row["spawnPosition"]
            self._movement.place(agent.agent_id, Position(spawn["x"], spawn["y"]), row["defaultRoom"])
            self._patrol_index[agent.agent_id] = 0
        self._placed = True

    def _intended_destination(self, agent_id: str, state: WorldState) -> tuple[Position, str]:
        """Where should this agent be heading this tick? Static positions
        come from `spatial_placement.json`; which one applies is driven
        only by `WorldState` signals — same "no invented events" rule as
        `behavior.determine_behavior`."""
        row = self._spatial.get(agent_id)
        agent = next((a for a in state.agents if a.agent_id == agent_id), None)
        if row is None or agent is None:
            pos = self._movement.current_position(agent_id) or Position(0.0, 0.0)
            room = self._movement.current_room(agent_id) or ""
            return pos, room

        room_id = agent.current_room_id
        room_events = [e for e in state.events if e.district == room_id]

        if any(e.severity == "critical" for e in room_events):
            p = row["emergencyPosition"]
            return Position(p["x"], p["y"]), room_id

        if room_id in resolve_active_meetings(state):
            p = row["meetingPosition"]
            return Position(p["x"], p["y"]), room_id

        if agent.status == "working":
            p = row["workingPosition"]
            return Position(p["x"], p["y"]), room_id

        if room_id == "recovery-center" and not agent.is_active:
            p = row["idlePosition"]
            return Position(p["x"], p["y"]), room_id

        # Idle: cycle the patrol route, advancing only once the current
        # waypoint is reached.
        patrol = row.get("patrolRoute") or [row["idlePosition"]]
        if self._movement.has_arrived(agent_id):
            self._patrol_index[agent_id] = (self._patrol_index.get(agent_id, 0) + 1) % len(patrol)
        p = patrol[self._patrol_index.get(agent_id, 0)]
        return Position(p["x"], p["y"]), row["defaultRoom"]

    # -- public API ----------------------------------------------------

    def step(self, force: bool = False) -> SimulationState:
        """Advance the simulation by exactly one tick and return the new
        `SimulationState` (also recorded into the timeline)."""
        state = self._get_world_state()
        self._ensure_placed(state)
        self._scheduler.should_tick(state.sequence, force=force)  # bookkeeping only, see class docstring
        self._scheduler.mark_ticked(state.sequence)

        tick_number, simulated_seconds = self._clock.advance()

        characters = []
        for agent in state.agents:
            target_pos, target_room = self._intended_destination(agent.agent_id, state)
            current_pos = self._movement.current_position(agent.agent_id) or target_pos
            current_room = self._movement.current_room(agent.agent_id) or target_room
            if (target_room, (target_pos.x, target_pos.y)) != (current_room, (current_pos.x, current_pos.y)):
                self._movement.set_destination(agent.agent_id, target_pos, target_room)
            new_pos = self._movement.step(agent.agent_id)
            behavior = determine_behavior(agent.agent_id, state, self._movement)
            characters.append(CharacterActivity(
                agent_id=agent.agent_id,
                agent_ref=agent.agent_ref,
                behavior=behavior,
                room_id=self._movement.current_room(agent.agent_id) or agent.current_room_id,
                position=new_pos,
                target_position=None if self._movement.has_arrived(agent.agent_id) else target_pos,
            ))

        rooms = tuple(
            RoomActivityState(
                room_id=r.room_id,
                activity=determine_room_activity(r, state),
                occupant_count=len(r.occupant_agent_ids),
            )
            for r in state.rooms
        )

        events = build_event_descriptors(state)

        sim_state = SimulationState(
            tick=SimulationTick(
                tick_number=tick_number,
                simulated_seconds=simulated_seconds,
                world_sequence=state.sequence,
            ),
            running=self._running,
            characters=tuple(characters),
            rooms=rooms,
            events=events,
        )
        self._timeline.record(sim_state)
        return sim_state

    def pause(self) -> None:
        self._running = False
        self._timeline.pause()

    def resume(self) -> None:
        self._running = True
        self._timeline.resume()

    def reset(self) -> None:
        self._clock.reset()
        self._scheduler.reset()
        self._movement = MovementController()
        self._timeline.reset()
        self._patrol_index = {}
        self._running = True
        self._placed = False

    @property
    def timeline(self) -> Timeline:
        return self._timeline

    @property
    def scheduler(self) -> SimulationScheduler:
        return self._scheduler

    @property
    def is_running(self) -> bool:
        return self._running

    def current_state(self) -> SimulationState | None:
        return self._timeline.current()
