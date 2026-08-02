"""EventBus — Phase W9's plain in-memory pub/sub for the six interaction
event types the brief names: SelectionChanged, HoverChanged, CameraMoved,
TimelineChanged, SimulationPaused, SimulationResumed.

Deliberately not a framework: a callable list per event name, called
synchronously in `publish()`. Matches this codebase's existing bias
against introducing dependencies for what a ~20-line class already does
(see `world.frontend.renderer.scene_cache.SceneCache`'s docstring making
the same call about `functools.lru_cache`).
"""

from dataclasses import dataclass, field
from typing import Callable

#: The six event types the phase brief names.
EVENT_TYPES = (
    "SelectionChanged", "HoverChanged", "CameraMoved",
    "TimelineChanged", "SimulationPaused", "SimulationResumed",
)


@dataclass(frozen=True)
class InteractionEvent:
    """One published event. `payload` is a plain dict (already
    `to_dict()`-shaped by whoever publishes it) rather than a union of
    every possible model type, so `EventBus` itself never needs to know
    about `world.interaction.models`."""

    event_type: str  # one of EVENT_TYPES
    payload: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"eventType": self.event_type, "payload": dict(self.payload)}


class EventBus:
    """In-memory, per-instance pub/sub. Each `world.interaction.api`
    caller gets its own `EventBus` (constructed alongside the rest of
    that caller's interaction managers) rather than a shared
    module-level singleton — matches how `world.frontend.renderer.
    renderer.SceneGraphRenderer` is constructed per-caller, not shared."""

    def __init__(self) -> None:
        self._subscribers: dict[str, list[Callable[[InteractionEvent], None]]] = {
            event_type: [] for event_type in EVENT_TYPES
        }
        self._log: list[InteractionEvent] = []

    def subscribe(self, event_type: str, handler: Callable[[InteractionEvent], None]) -> None:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type {event_type!r}; must be one of {EVENT_TYPES}")
        self._subscribers[event_type].append(handler)

    def publish(self, event_type: str, payload: dict | None = None) -> InteractionEvent:
        if event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type {event_type!r}; must be one of {EVENT_TYPES}")
        event = InteractionEvent(event_type=event_type, payload=dict(payload or {}))
        self._log.append(event)
        for handler in self._subscribers[event_type]:
            handler(event)
        return event

    def history(self, event_type: str | None = None) -> tuple[InteractionEvent, ...]:
        if event_type is None:
            return tuple(self._log)
        return tuple(e for e in self._log if e.event_type == event_type)

    def clear_history(self) -> None:
        self._log = []
