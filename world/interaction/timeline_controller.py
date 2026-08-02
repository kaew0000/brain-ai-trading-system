"""TimelineController — Timeline section (Seek, Replay, Pause, Resume,
Jump to event, history navigation).

Thin wrapper around `world.simulation.api.get_timeline()` (the Phase W9
addition to `world.simulation.api` exposing `SimulationEngine`'s
`Timeline`). Adds exactly one thing `Timeline` itself doesn't have:
`jump_to_event`, since `Timeline.seek()` only takes a `tick_number` and
the brief asks for "Jump to Event" by event, not by tick — this resolves
an `event_id` to the tick that produced it (an event's `EventDescriptor`
has no tick number of its own; it's only ever seen attached to the
`SimulationState` that `SimulationEngine.step()` built it into) and then
delegates to `Timeline.seek()`.

Does not wrap `SimulationEngine.step()`/`pause()`/`resume()` themselves —
those belong to `command_dispatcher.py`, which is also responsible for
publishing `TimelineChanged`/`SimulationPaused`/`SimulationResumed`
events. This class is read/seek-only.
"""

from world.simulation import api as simulation_api
from world.simulation.models import SimulationState


class UnknownEventError(ValueError):
    """Raised by `jump_to_event` when no retained tick produced this
    `event_id` — either it never existed, or it has aged out of
    `Timeline`'s `history_window`."""


class TimelineController:
    def __init__(self, get_timeline=simulation_api.get_timeline) -> None:
        self._get_timeline = get_timeline

    def current(self) -> SimulationState | None:
        return self._get_timeline().current()

    def seek(self, tick_number: int) -> SimulationState | None:
        return self._get_timeline().seek(tick_number)

    def jump_to_event(self, event_id: str) -> SimulationState:
        timeline = self._get_timeline()
        for state in getattr(timeline, "_records", ()):
            if any(e.event_id == event_id for e in state.events):
                result = timeline.seek(state.tick.tick_number)
                if result is not None:
                    return result
        raise UnknownEventError(f"no retained tick produced event {event_id!r}")

    def play(self) -> None:
        self._get_timeline().play()

    def pause(self) -> None:
        self._get_timeline().pause()

    def resume(self) -> None:
        self._get_timeline().resume()

    def is_playing(self) -> bool:
        return self._get_timeline().is_playing()

    def length(self) -> int:
        return len(self._get_timeline())
