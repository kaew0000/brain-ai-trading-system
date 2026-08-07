"""world/workspace/history.py — Phase W12, Feature 8.

Remembers selected object / camera / opened panels / commands / timeline
location, as a simple append-only, bounded, in-memory list — same
"in-memory, bounded, not persisted" discipline
`world.interaction.InteractionHistory` (Phase W9) already uses. "Undo
navigation only" per this phase's own brief: `undo()` moves the cursor
back and returns the entry to restore to, but never re-executes a
command or mutates any other module's state itself — the caller (the
frontend, or `api.py`) is responsible for actually re-applying whatever
the returned entry describes.
"""

from dataclasses import dataclass, field

from world.workspace.models import HistoryEntry

DEFAULT_MAX_ENTRIES = 200


@dataclass
class NavigationHistory:
    max_entries: int = DEFAULT_MAX_ENTRIES
    _entries: list = field(default_factory=list)
    _cursor: int = -1
    _next_id: int = 1

    def record(self, kind: str, payload: dict, timestamp: str) -> HistoryEntry:
        entry = HistoryEntry(entry_id=self._next_id, kind=kind, payload=payload, timestamp=timestamp)
        self._next_id += 1
        # Recording after an undo discards the "future" (standard undo-stack
        # semantics), same as `Timeline.record()` when playing.
        self._entries = self._entries[: self._cursor + 1]
        self._entries.append(entry)
        if len(self._entries) > self.max_entries:
            overflow = len(self._entries) - self.max_entries
            self._entries = self._entries[overflow:]
        self._cursor = len(self._entries) - 1
        return entry

    def undo(self) -> HistoryEntry | None:
        if self._cursor <= 0:
            return None
        self._cursor -= 1
        return self._entries[self._cursor]

    def current(self) -> HistoryEntry | None:
        if 0 <= self._cursor < len(self._entries):
            return self._entries[self._cursor]
        return None

    def all_entries(self) -> tuple[HistoryEntry, ...]:
        return tuple(self._entries)

    def reset(self) -> None:
        self._entries = []
        self._cursor = -1
        self._next_id = 1

    def __len__(self) -> int:
        return len(self._entries)
