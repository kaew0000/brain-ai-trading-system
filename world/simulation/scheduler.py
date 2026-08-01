"""SimulationScheduler — decides *whether* `SimulationEngine` should
rebuild its `SimulationState`, the same way `world.runtime.update_manager.
UpdateManager` decides whether `StateBuilder` should rebuild: by comparing
the current `WorldState.sequence` to the one the last tick was built from.

No polling loop lives here either — `should_tick()` only checks when
`SimulationEngine.step()` calls it. `fps_target` is a logical constant
(Part H's "simulation FPS target"): how many ticks *would* happen per
second if something external called `step()` at that rate. Nothing here
enforces or measures real wall-clock timing against it."""

from dataclasses import dataclass

#: Logical-only design target — see Part H. Not enforced by this class;
#: purely descriptive for `world.simulation.statistics`.
DEFAULT_FPS_TARGET = 1.0


@dataclass
class SimulationScheduler:
    fps_target: float = DEFAULT_FPS_TARGET
    _last_world_sequence: int | None = None

    def should_tick(self, world_sequence: int, force: bool = False) -> bool:
        """A tick is needed if forced, if this is the first call, or if
        the underlying `WorldState` has actually changed since the last
        tick this scheduler approved."""
        if force or self._last_world_sequence is None:
            return True
        return world_sequence != self._last_world_sequence

    def mark_ticked(self, world_sequence: int) -> None:
        self._last_world_sequence = world_sequence

    def reset(self) -> None:
        self._last_world_sequence = None
