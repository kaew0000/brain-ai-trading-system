"""Phase W9 interaction-layer models.

Every model here is a frozen dataclass with a `to_dict()`, matching the
convention `world.runtime.models` and `world.simulation.models` already
established. Nothing here mutates `world.runtime` or `world.simulation`
state — these are read-only views built *from* that state.

`SelectionKind` mirrors the six selectable object types from the phase
brief (Room, Character, Department, Furniture, Decoration, Simulation
event). "Department" and "Room" are the same underlying id space in this
codebase (`world.runtime.models.RoomState.room_id` — departments *are*
rooms here, see `world/docs/OFFICE_LAYOUT.md`), so both kinds resolve
against the same room lookup; they are kept as two labels because the
brief lists them separately and a caller may reasonably want to know
which noun the user actually clicked.
"""

from dataclasses import dataclass, field

#: What can be selected/hovered — Selection + Hover Systems.
SELECTION_KINDS = ("room", "character", "department", "furniture", "decoration", "event")

#: Notification categories the phase brief names, derived only from
#: `world.simulation.models.SimulationState` (see `notification_center.py`).
NOTIFICATION_CATEGORIES = (
    "emergency", "meeting", "alert", "mission", "celebration", "system_status",
)


@dataclass(frozen=True)
class Selection:
    """The currently selected object, if any."""

    kind: str  # one of SELECTION_KINDS
    target_id: str

    def to_dict(self) -> dict:
        return {"kind": self.kind, "targetId": self.target_id}


@dataclass(frozen=True)
class HoverInfo:
    """What the Hover System shows for one target — Part: Hover System.
    `status`/`activity` come from the simulation layer (a character's
    behavior, or a room's activity level); `room_info` is a short label,
    not a full `InspectorReport` (hover is meant to be light-weight)."""

    target_id: str
    kind: str
    status: str = ""
    activity: str = ""
    room_info: str = ""
    simulation_clock: dict = field(default_factory=dict)
    current_event: str = ""

    def to_dict(self) -> dict:
        return {
            "targetId": self.target_id,
            "kind": self.kind,
            "status": self.status,
            "activity": self.activity,
            "roomInfo": self.room_info,
            "simulationClock": dict(self.simulation_clock),
            "currentEvent": self.current_event,
        }


@dataclass(frozen=True)
class HistoryEntry:
    """One entry in an `InspectorReport.historical_timeline` — a past
    `SimulationState` tick in which this target appeared, not a full
    `SimulationState` (that would duplicate `Timeline`'s own storage;
    this only records enough to jump back via `Timeline.seek()`)."""

    tick_number: int
    behavior_or_activity: str
    room_id: str

    def to_dict(self) -> dict:
        return {
            "tickNumber": self.tick_number,
            "behaviorOrActivity": self.behavior_or_activity,
            "roomId": self.room_id,
        }


@dataclass(frozen=True)
class InspectorReport:
    """Everything the Inspector Panel section of the brief asks for, for
    one selected object. Fields that don't apply to a given `kind` are
    left at their default (empty string / empty tuple) rather than
    omitted, so a caller can always read every field without a
    kind-specific branch."""

    id: str
    name: str
    kind: str  # one of SELECTION_KINDS
    current_state: str = ""
    location: str = ""
    simulation_status: str = ""
    assigned_agent: str = ""
    current_activity: str = ""
    historical_timeline: tuple[HistoryEntry, ...] = field(default_factory=tuple)
    linked_runtime_data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "kind": self.kind,
            "currentState": self.current_state,
            "location": self.location,
            "simulationStatus": self.simulation_status,
            "assignedAgent": self.assigned_agent,
            "currentActivity": self.current_activity,
            "historicalTimeline": [h.to_dict() for h in self.historical_timeline],
            "linkedRuntimeData": dict(self.linked_runtime_data),
        }


@dataclass(frozen=True)
class InteractionNotification:
    """One Notification Center entry. Built only from
    `world.simulation.models.SimulationState` per the phase brief
    ("Notifications consume SimulationState only") — see
    `notification_center.py` for exactly how `category` is derived."""

    notification_id: str
    category: str  # one of NOTIFICATION_CATEGORIES
    room_id: str
    tick_number: int
    message: str = ""
    agent_id: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.notification_id,
            "category": self.category,
            "roomId": self.room_id,
            "tickNumber": self.tick_number,
            "message": self.message,
            "agentId": self.agent_id,
        }


@dataclass(frozen=True)
class CommandResult:
    """Result of one `command_dispatcher.dispatch()` call."""

    command: str
    ok: bool
    detail: str = ""
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"command": self.command, "ok": self.ok, "detail": self.detail, "data": dict(self.data)}
