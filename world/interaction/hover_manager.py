"""HoverManager — Hover System.

Deliberately lighter than `inspector.build_inspector_report`: a hover is a
transient, high-frequency event (potentially every mouse-move), so this
only reads `world.simulation.api.get_simulation_state()` once per call and
does no `world.runtime` lookups beyond a room-name lookup, unlike the full
Inspector Panel which also merges static runtime identity and historical
timeline. Matches the brief's own split between "Hover System" (Status,
Activity, Room information, Simulation clock, Current event) and the
richer "Inspector Panel" section.
"""

from world.interaction.models import HoverInfo
from world.runtime import api as runtime_api
from world.simulation import api as simulation_api


class HoverManager:
    def __init__(
        self,
        get_simulation_state=simulation_api.get_simulation_state,
        get_room_state=runtime_api.get_room_state,
    ) -> None:
        self._get_simulation_state = get_simulation_state
        self._get_room_state = get_room_state

    def hover(self, kind: str, target_id: str) -> HoverInfo:
        sim_state = self._get_simulation_state()
        clock = sim_state.tick.to_dict()

        if kind == "character":
            activity = next((c for c in sim_state.characters if c.agent_id == target_id), None)
            if activity is None:
                return HoverInfo(target_id=target_id, kind=kind, simulation_clock=clock)
            room = self._get_room_state(activity.room_id)
            current_event = next((e.message for e in sim_state.events if e.agent_id == target_id), "")
            return HoverInfo(
                target_id=target_id, kind=kind, status=activity.behavior,
                room_info=room.name if room else activity.room_id,
                simulation_clock=clock, current_event=current_event,
            )

        if kind in ("room", "department"):
            room_activity = next((r for r in sim_state.rooms if r.room_id == target_id), None)
            room = self._get_room_state(target_id)
            current_event = next((e.message for e in sim_state.events if e.room_id == target_id), "")
            return HoverInfo(
                target_id=target_id, kind=kind,
                activity=room_activity.activity if room_activity else "",
                room_info=room.name if room else target_id,
                simulation_clock=clock, current_event=current_event,
            )

        # furniture / decoration / event: no per-tick behaviour/activity of
        # their own — hover still returns the simulation clock so a caller
        # always gets a consistent HoverInfo shape.
        return HoverInfo(target_id=target_id, kind=kind, simulation_clock=clock)
