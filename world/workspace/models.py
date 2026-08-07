"""world/workspace/models.py — Phase W12.

Frozen dataclasses, matching every prior phase's convention
(`world.runtime.models`, `world.simulation.models`, `world.interaction.
models`). Every field here is derived from data `world.runtime`,
`world.simulation`, or `world.interaction` already expose — nothing in
this package computes a trading figure or imports from Track A.
"""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class PanelLayout:
    panel_id: str
    x: float
    y: float
    width: float
    height: float
    collapsed: bool = False
    docked: bool = True
    z_order: int = 0

    def to_dict(self) -> dict:
        return {
            "panelId": self.panel_id, "x": self.x, "y": self.y,
            "width": self.width, "height": self.height,
            "collapsed": self.collapsed, "docked": self.docked, "zOrder": self.z_order,
        }

    @staticmethod
    def from_dict(d: dict) -> "PanelLayout":
        return PanelLayout(
            panel_id=d["panelId"], x=d["x"], y=d["y"], width=d["width"], height=d["height"],
            collapsed=d.get("collapsed", False), docked=d.get("docked", True), z_order=d.get("zOrder", 0),
        )


@dataclass(frozen=True)
class WorkspaceLayout:
    """The whole persisted layout — every `PanelLayout` plus which
    panels are currently open. Saved verbatim to
    `world/data/runtime/workspace.json`; nothing here is derived from
    live state, so persistence never needs the WorldState/SimulationState
    pipeline at all."""

    panels: tuple[PanelLayout, ...] = field(default_factory=tuple)
    open_panel_ids: tuple[str, ...] = field(default_factory=tuple)
    version: int = 1

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "panels": [p.to_dict() for p in self.panels],
            "openPanelIds": list(self.open_panel_ids),
        }

    @staticmethod
    def from_dict(d: dict) -> "WorkspaceLayout":
        return WorkspaceLayout(
            panels=tuple(PanelLayout.from_dict(p) for p in d.get("panels", [])),
            open_panel_ids=tuple(d.get("openPanelIds", [])),
            version=d.get("version", 1),
        )


@dataclass(frozen=True)
class AgentPanelState:
    """One of the 7 named agent panels (Feature 2). `heartbeat_age_s`
    and `latency_ms` are best-effort — see `agent_workspace.py`'s own
    docstring for why they can legitimately be `None` (no verified
    per-agent telemetry-key mapping exists — same honest-gap discipline
    Phase W11 documented for event->room mapping)."""

    panel_label: str
    agent_id: str
    room_id: str
    status: str
    heartbeat_age_s: float | None
    latency_ms: float | None
    last_decision: str | None
    current_task: str | None
    last_update: str

    def to_dict(self) -> dict:
        return {
            "panelLabel": self.panel_label, "agentId": self.agent_id, "roomId": self.room_id,
            "status": self.status, "heartbeatAgeSeconds": self.heartbeat_age_s,
            "latencyMs": self.latency_ms, "lastDecision": self.last_decision,
            "currentTask": self.current_task, "lastUpdate": self.last_update,
        }


@dataclass(frozen=True)
class OperationsSummary:
    """Feature 3 — top strip. Every field nullable/honest-default when
    the underlying WorldState doesn't have it yet."""

    mode: str
    engine_status: str
    account_equity: float | None
    drawdown: float | None
    active_mission_count: int
    exchange_connected: bool
    heartbeat_age_s: float | None
    cpu_percent: float | None
    ram_percent: float | None
    clock: str

    def to_dict(self) -> dict:
        return {
            "mode": self.mode, "engineStatus": self.engine_status,
            "accountEquity": self.account_equity, "drawdown": self.drawdown,
            "activeMissionCount": self.active_mission_count,
            "exchangeConnected": self.exchange_connected,
            "heartbeatAgeSeconds": self.heartbeat_age_s,
            "cpuPercent": self.cpu_percent, "ramPercent": self.ram_percent, "clock": self.clock,
        }


@dataclass(frozen=True)
class NotificationDockItem:
    """Wraps a real `world.interaction.models.InteractionNotification`
    (category/room_id/tick_number/message/agent_id — no timestamp,
    severity, or read field at that layer) plus the two purely
    workspace-tracked flags (`read`, `pinned`) this feature adds on top,
    same as `pinned` for NotificationDockStore."""

    notification_id: str
    category: str  # one of world.interaction.models.NOTIFICATION_CATEGORIES
    room_id: str
    tick_number: int
    message: str
    agent_id: str
    read: bool
    pinned: bool

    def to_dict(self) -> dict:
        return {
            "id": self.notification_id, "category": self.category, "roomId": self.room_id,
            "tickNumber": self.tick_number, "message": self.message, "agentId": self.agent_id,
            "read": self.read, "pinned": self.pinned,
        }


@dataclass(frozen=True)
class MissionWorkspaceItem:
    mission_id: str
    title: str
    district: str
    status: str
    bucket: str  # "waiting" | "active" | "completed" | "blocked"

    def to_dict(self) -> dict:
        return {
            "missionId": self.mission_id, "title": self.title, "district": self.district,
            "status": self.status, "bucket": self.bucket,
        }


@dataclass(frozen=True)
class SearchResult:
    kind: str  # room|agent|mission|department|notification|event|character|building
    result_id: str
    label: str
    detail: str = ""

    def to_dict(self) -> dict:
        return {"kind": self.kind, "id": self.result_id, "label": self.label, "detail": self.detail}


@dataclass(frozen=True)
class HistoryEntry:
    entry_id: int
    kind: str  # selection|camera|panel|command|timeline
    payload: dict
    timestamp: str

    def to_dict(self) -> dict:
        return {
            "entryId": self.entry_id, "kind": self.kind,
            "payload": self.payload, "timestamp": self.timestamp,
        }


@dataclass(frozen=True)
class PerformanceOverlayState:
    """Feature 9 — logical timings only, no profiling library. `fps` is
    the Phase W7 `simulation_fps_target` design constant re-exposed, not
    a measured frame rate (nothing in this Python backend renders
    frames) — see `performance_overlay.py`'s own docstring."""

    fps_target: float
    world_update_seconds: float
    simulation_update_seconds: float
    render_seconds: float | None
    memory_kb: float
    cpu_percent: float | None

    def to_dict(self) -> dict:
        return {
            "fpsTarget": self.fps_target,
            "worldUpdateSeconds": self.world_update_seconds,
            "simulationUpdateSeconds": self.simulation_update_seconds,
            "renderSeconds": self.render_seconds,
            "memoryKb": self.memory_kb,
            "cpuPercent": self.cpu_percent,
        }
