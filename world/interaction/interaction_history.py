"""InteractionHistory — a log of *user interactions* (selections,
commands issued), distinct from `world.simulation.timeline.Timeline`
(which records *simulation ticks*). The brief's "History navigation"
item under Timeline and its "History" item under Tests both name this
concern separately from Timeline's own play/pause/seek, so it gets its
own small class rather than being folded into `TimelineController`.

A rolling window, same bounded-memory rationale as `Timeline`
(`history_window`) and `world.runtime.state_cache` — an interaction
session that runs indefinitely should not grow this list unboundedly.
"""

from dataclasses import dataclass, field

DEFAULT_HISTORY_WINDOW = 200


@dataclass(frozen=True)
class InteractionRecord:
    kind: str  # "selection" | "command"
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"kind": self.kind, "detail": dict(self.detail)}


class InteractionHistory:
    def __init__(self, history_window: int = DEFAULT_HISTORY_WINDOW) -> None:
        if history_window < 1:
            raise ValueError("history_window must be at least 1")
        self._window = history_window
        self._records: list[InteractionRecord] = []

    def record_selection(self, kind: str, target_id: str) -> None:
        self._append(InteractionRecord(kind="selection", detail={"selectionKind": kind, "targetId": target_id}))

    def record_command(self, command: str, ok: bool, detail: str = "") -> None:
        self._append(InteractionRecord(kind="command", detail={"command": command, "ok": ok, "detail": detail}))

    def _append(self, record: InteractionRecord) -> None:
        self._records.append(record)
        if len(self._records) > self._window:
            self._records = self._records[-self._window:]

    def all(self) -> tuple[InteractionRecord, ...]:
        return tuple(self._records)

    def clear(self) -> None:
        self._records = []

    def __len__(self) -> int:
        return len(self._records)
