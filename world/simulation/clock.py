"""SimulationClock — logical time only. Never reads the wall clock to
decide *whether* to advance (that's `SimulationScheduler`'s job); this
class just counts ticks and the logical seconds they represent, so replays
via `Timeline.seek()` are reproducible regardless of how much real time
elapsed between calls."""

from dataclasses import dataclass

#: Logical seconds one tick represents. A design constant, not a real-time
#: guarantee — nothing here sleeps or blocks.
SECONDS_PER_TICK = 1.0


@dataclass
class SimulationClock:
    tick_number: int = 0
    simulated_seconds: float = 0.0

    def advance(self) -> tuple[int, float]:
        """Advance by exactly one tick. Returns the new
        `(tick_number, simulated_seconds)`."""
        self.tick_number += 1
        self.simulated_seconds += SECONDS_PER_TICK
        return self.tick_number, self.simulated_seconds

    def reset(self) -> None:
        self.tick_number = 0
        self.simulated_seconds = 0.0
