"""Timeline — Part F. Records every `SimulationState` `SimulationEngine`
produces and lets something (a future interactive layer, a test, a
debugging session) play/pause/resume/seek through that history. No video,
no rendering — this is a plain in-memory list plus a cursor.

`history_window` bounds memory by dropping the oldest recorded states once
the limit is exceeded (a rolling window), the same "don't grow unbounded"
concern `world.runtime.state_cache` addresses for a single cached state,
applied here to a whole history instead.
"""

from world.simulation.models import SimulationState


class Timeline:
    def __init__(self, history_window: int | None = None) -> None:
        self._history_window = history_window
        self._records: list[SimulationState] = []
        self._cursor = -1
        self._playing = True

    def record(self, state: SimulationState) -> None:
        """Append a new state. If playing, the cursor follows it (the
        "live" position); if paused, the cursor stays where it was so a
        paused review isn't yanked forward by new ticks arriving."""
        self._records.append(state)
        if self._history_window is not None and len(self._records) > self._history_window:
            overflow = len(self._records) - self._history_window
            self._records = self._records[overflow:]
            self._cursor = max(-1, self._cursor - overflow)
        if self._playing:
            self._cursor = len(self._records) - 1

    def play(self) -> None:
        """Start/restart playback from the beginning of retained history."""
        self._playing = True
        self._cursor = 0 if self._records else -1

    def pause(self) -> None:
        self._playing = False

    def resume(self) -> None:
        """Continue playback from wherever the cursor currently is (unlike
        `play()`, does not reset to the beginning)."""
        self._playing = True
        if self._records:
            self._cursor = len(self._records) - 1

    def seek(self, tick_number: int) -> SimulationState | None:
        """Move the cursor to the recorded state with this `tick_number`,
        pausing playback (seeking implies "let me look at this one").
        Returns `None`, leaving the cursor unchanged, if no such tick is
        in the retained history window."""
        for i, state in enumerate(self._records):
            if state.tick.tick_number == tick_number:
                self._cursor = i
                self._playing = False
                return state
        return None

    def current(self) -> SimulationState | None:
        if 0 <= self._cursor < len(self._records):
            return self._records[self._cursor]
        return None

    def is_playing(self) -> bool:
        return self._playing

    def __len__(self) -> int:
        return len(self._records)

    def reset(self) -> None:
        self._records = []
        self._cursor = -1
        self._playing = True
