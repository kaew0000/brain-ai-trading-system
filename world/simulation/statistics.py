"""world.simulation.statistics — Part H. Pure function of a
`SimulationState` plus a `Timeline` (for `timeline_length`) and a
`SimulationScheduler` (for `simulation_fps_target`). Nothing here mutates
anything.

All percentages are of the *current tick's* population, not a cumulative
average across the whole session — consistent with every other field
here describing "right now," matching how `world.runtime.statistics`
reports counts for the current `WorldState` rather than history.
"""

from dataclasses import dataclass

from world.simulation.models import SimulationState
from world.simulation.scheduler import SimulationScheduler
from world.simulation.timeline import Timeline

_ALERT_ACTIVITIES = frozenset({"alert", "critical"})


@dataclass(frozen=True)
class SimulationStatistics:
    active_characters: int
    active_rooms: int
    movement_count: int
    meeting_count: int
    idle_percentage: float
    alert_percentage: float
    timeline_length: int
    simulation_fps_target: float

    def to_dict(self) -> dict:
        return {
            "activeCharacters": self.active_characters,
            "activeRooms": self.active_rooms,
            "movementCount": self.movement_count,
            "meetingCount": self.meeting_count,
            "idlePercentage": self.idle_percentage,
            "alertPercentage": self.alert_percentage,
            "timelineLength": self.timeline_length,
            "simulationFpsTarget": self.simulation_fps_target,
        }


def compute_statistics(
    state: SimulationState,
    timeline: Timeline,
    scheduler: SimulationScheduler,
) -> SimulationStatistics:
    total_characters = len(state.characters) or 1
    total_rooms = len(state.rooms) or 1

    active_characters = sum(1 for c in state.characters if c.behavior != "idle")
    active_rooms = sum(1 for r in state.rooms if r.activity != "quiet")
    movement_count = sum(1 for c in state.characters if c.behavior == "walking")
    meeting_count = sum(1 for c in state.characters if c.behavior == "meeting")
    idle_count = sum(1 for c in state.characters if c.behavior == "idle")
    alert_count = sum(1 for r in state.rooms if r.activity in _ALERT_ACTIVITIES)

    return SimulationStatistics(
        active_characters=active_characters,
        active_rooms=active_rooms,
        movement_count=movement_count,
        meeting_count=meeting_count,
        idle_percentage=(idle_count / total_characters) * 100.0,
        alert_percentage=(alert_count / total_rooms) * 100.0,
        timeline_length=len(timeline),
        simulation_fps_target=scheduler.fps_target,
    )
