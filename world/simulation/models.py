"""Phase W7 simulation models.

Everything here is a frozen dataclass, mirroring the Phase W5 convention
(`world/runtime/models.py`). Nothing here imports from `world.frontend`
(no renderer-specific code, per this phase's own constraint) — a
`SimulationState` is pure logical/visualization state, not a scene graph.

Behavior/activity values are plain strings rather than a Python `Enum`, to
match how `world.runtime.models` already represents `AgentState.status`
and mission status — kept consistent rather than introducing a new
pattern for one layer.
"""

from dataclasses import dataclass, field

#: Character behaviour states — Part B.
CHARACTER_BEHAVIORS = (
    "idle", "walking", "working", "meeting", "emergency", "celebration", "resting",
)

#: Room activity states — Part C.
ROOM_ACTIVITIES = (
    "quiet", "busy", "meeting", "alert", "critical", "celebration",
)

#: Event descriptor kinds — Part E.
EVENT_KINDS = (
    "trade_opened", "trade_closed", "risk_alert", "portfolio_growth",
    "system_recovery", "notification",
)


@dataclass(frozen=True)
class Position:
    x: float
    y: float

    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}


@dataclass(frozen=True)
class CharacterActivity:
    """One character's simulated behaviour at a tick."""

    agent_id: str
    agent_ref: str
    behavior: str  # one of CHARACTER_BEHAVIORS
    room_id: str
    position: Position
    target_position: Position | None = None

    def to_dict(self) -> dict:
        return {
            "agentId": self.agent_id,
            "agentRef": self.agent_ref,
            "behavior": self.behavior,
            "roomId": self.room_id,
            "position": self.position.to_dict(),
            "targetPosition": self.target_position.to_dict() if self.target_position else None,
        }


@dataclass(frozen=True)
class RoomActivityState:
    """One room's simulated activity level at a tick. Named
    `RoomActivityState` (not `RoomActivity`) to avoid shadowing the
    `activity` field name it carries."""

    room_id: str
    activity: str  # one of ROOM_ACTIVITIES
    occupant_count: int = 0

    def to_dict(self) -> dict:
        return {
            "roomId": self.room_id,
            "activity": self.activity,
            "occupantCount": self.occupant_count,
        }


@dataclass(frozen=True)
class EventDescriptor:
    """Metadata-only event descriptor — Part E. No graphics, no renderer
    hints; just enough for a future interactive layer to decide what to
    show and where."""

    event_id: str
    kind: str  # one of EVENT_KINDS
    room_id: str
    agent_id: str = ""
    timestamp: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "eventId": self.event_id,
            "kind": self.kind,
            "roomId": self.room_id,
            "agentId": self.agent_id,
            "timestamp": self.timestamp,
            "message": self.message,
        }


@dataclass(frozen=True)
class SimulationTick:
    """One logical tick. `simulated_seconds` is a logical counter (ticks
    since reset), not a wall-clock reading — `SimulationClock` is the only
    thing that advances it, and only when asked."""

    tick_number: int
    simulated_seconds: float
    world_sequence: int

    def to_dict(self) -> dict:
        return {
            "tickNumber": self.tick_number,
            "simulatedSeconds": self.simulated_seconds,
            "worldSequence": self.world_sequence,
        }


@dataclass(frozen=True)
class SimulationState:
    """The immutable, in-memory aggregate `SimulationEngine.step()`
    produces — the Phase W7 analogue of Phase W5's `WorldState`."""

    tick: SimulationTick
    running: bool = True
    characters: tuple[CharacterActivity, ...] = field(default_factory=tuple)
    rooms: tuple[RoomActivityState, ...] = field(default_factory=tuple)
    events: tuple[EventDescriptor, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "tick": self.tick.to_dict(),
            "running": self.running,
            "characters": [c.to_dict() for c in self.characters],
            "rooms": [r.to_dict() for r in self.rooms],
            "events": [e.to_dict() for e in self.events],
        }
