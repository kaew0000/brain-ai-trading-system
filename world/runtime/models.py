"""Phase W5 backend world-state models.

These are intentionally a *richer, backend-internal* representation than
`world.frontend.renderer.world_state.WorldState` (Phase W3) — that class is
the flattened, renderer-facing shape (`district_status`, `character_states`,
`character_positions`, `recent_events`, `sequence`) a concrete `Renderer`
consumes. This module's `WorldState` is what the backend builds and
validates *before* any such projection happens.

Binding this richer state to the Phase W3 `WorldStateProvider` ABC (i.e.
implementing `get_current_state() -> world.frontend.renderer.world_state.WorldState`
by projecting a `world.runtime.models.WorldState` down to the flattened
shape) is explicitly deferred to Phase W6 (Renderer Integration), per this
phase's own success criteria: "No renderer exists yet." Nothing in this
module imports from `world.frontend.renderer` or `world.frontend.interfaces`.

Every model is a frozen dataclass using tuples (not lists) for collection
fields, so a `WorldState` instance is fully immutable and hashable-by-value
where its contents allow. Every model has a `to_dict()` for JSON
serialization; nothing here writes to disk itself.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RoomState:
    """One department (or lobby/hallway/elevator) at a point in time."""

    room_id: str
    name: str
    occupant_agent_ids: tuple[str, ...] = ()
    active_mission_ids: tuple[str, ...] = ()
    is_active: bool = False

    def to_dict(self) -> dict:
        return {
            "roomId": self.room_id,
            "name": self.name,
            "occupantAgentIds": list(self.occupant_agent_ids),
            "activeMissionIds": list(self.active_mission_ids),
            "isActive": self.is_active,
        }


@dataclass(frozen=True)
class AgentState:
    """One character/agent at a point in time."""

    agent_id: str
    agent_ref: str
    current_room_id: str
    is_active: bool = False
    status: str = "idle"

    def to_dict(self) -> dict:
        return {
            "agentId": self.agent_id,
            "agentRef": self.agent_ref,
            "currentRoomId": self.current_room_id,
            "isActive": self.is_active,
            "status": self.status,
        }


@dataclass(frozen=True)
class MissionState:
    mission_id: str
    title: str
    district: str
    status: str
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "missionId": self.mission_id,
            "title": self.title,
            "district": self.district,
            "status": self.status,
            "description": self.description,
        }


@dataclass(frozen=True)
class PortfolioState:
    symbol: str
    district: str = "portfolio-garden"
    size_label: str = ""

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "district": self.district,
            "sizeLabel": self.size_label,
        }


@dataclass(frozen=True)
class NotificationState:
    notification_id: str
    timestamp: str
    message: str
    severity: str
    read: bool = False

    def to_dict(self) -> dict:
        return {
            "id": self.notification_id,
            "timestamp": self.timestamp,
            "message": self.message,
            "severity": self.severity,
            "read": self.read,
        }


@dataclass(frozen=True)
class EventState:
    """Not requested by name in the Phase W5 spec's model list, but Part A's
    own merge responsibilities name `events` explicitly — represented here
    rather than left as untyped dicts, for the same serializability/
    validation guarantees as every other model."""

    event_id: str
    timestamp: str
    event_type: str
    district: str
    severity: str
    agent: str = ""
    message: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.event_id,
            "timestamp": self.timestamp,
            "type": self.event_type,
            "district": self.district,
            "severity": self.severity,
            "agent": self.agent,
            "message": self.message,
        }


@dataclass(frozen=True)
class TelemetryState:
    """Same rationale as `EventState` — `telemetry` is named in Part A's
    merge responsibilities but not in the model list."""

    name: str
    value: float
    unit: str = ""
    district: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "district": self.district,
        }


@dataclass(frozen=True)
class WorldState:
    """The immutable, in-memory aggregate `StateBuilder.build()` produces.
    Every collection field is a tuple. Construct only via `StateBuilder` —
    this class itself does no reading, merging, or defaulting."""

    engine_status: str = "idle"
    version: str = "0.1.0"
    captured_at: str = ""
    sequence: int = 0

    rooms: tuple[RoomState, ...] = field(default_factory=tuple)
    agents: tuple[AgentState, ...] = field(default_factory=tuple)
    missions: tuple[MissionState, ...] = field(default_factory=tuple)
    portfolio: tuple[PortfolioState, ...] = field(default_factory=tuple)
    notifications: tuple[NotificationState, ...] = field(default_factory=tuple)
    events: tuple[EventState, ...] = field(default_factory=tuple)
    telemetry: tuple[TelemetryState, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict:
        return {
            "engineStatus": self.engine_status,
            "version": self.version,
            "capturedAt": self.captured_at,
            "sequence": self.sequence,
            "rooms": [r.to_dict() for r in self.rooms],
            "agents": [a.to_dict() for a in self.agents],
            "missions": [m.to_dict() for m in self.missions],
            "portfolio": [p.to_dict() for p in self.portfolio],
            "notifications": [n.to_dict() for n in self.notifications],
            "events": [e.to_dict() for e in self.events],
            "telemetry": [t.to_dict() for t in self.telemetry],
        }
