"""StateBuilder — turns the six Phase W4 runtime JSON files plus the
static Phase W1/W2 canon (department ids, character ids, desk placement)
into one immutable `world.runtime.models.WorldState`.

Reads only. Never mutates anything it loads — every value that ends up on
a model comes from a fresh `dict`/`list` built here, never a reference into
a loaded JSON structure that something else might still hold.

Missing/empty runtime files are treated as "no data yet" (Phase W4's own
documented behavior — see `world/docs/INGESTION_ADAPTER.md`), not errors:
every field gets a sensible default so `build()` always succeeds."""

import json
import os

from world.runtime.models import (
    AgentState,
    EventState,
    MissionState,
    NotificationState,
    OrderTimelineState,
    PortfolioState,
    PortfolioSummaryState,
    ReconciliationState,
    RoomState,
    TelemetryState,
    WorldState,
)

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/runtime
WORLD_ROOT = os.path.dirname(_THIS_DIR)  # world/

DEFAULT_RUNTIME_DIR = os.path.join(WORLD_ROOT, "data", "runtime")
DISTRICT_DEFS_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")
CHAR_DEFS_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")
PLACEMENT_PATH = os.path.join(WORLD_ROOT, "data", "characters", "placement.json")

_CIRCULATION_ROOMS = {
    "lobby": "Lobby",
    "hallway": "Hallway",
    "elevator": "Elevator",
}


def _load_json(path: str, default):
    """Read a JSON file; return `default` if it's missing, empty, or
    unreadable, rather than raising — matches Phase W4's own
    "missing source is fine" convention (see `world.adapter.adapter`)."""
    if not os.path.isfile(path):
        return default
    try:
        with open(path) as f:
            content = f.read().strip()
        if not content:
            return default
        return json.loads(content)
    except (OSError, json.JSONDecodeError):
        return default


class StateBuilder:
    """`build()` is the only public entry point. Constructed with the
    directories it reads from, so tests can point it at fixture data
    without touching `world/data/runtime/`."""

    def __init__(
        self,
        runtime_dir: str = DEFAULT_RUNTIME_DIR,
        district_defs_dir: str = DISTRICT_DEFS_DIR,
        char_defs_dir: str = CHAR_DEFS_DIR,
        placement_path: str = PLACEMENT_PATH,
    ) -> None:
        self._runtime_dir = runtime_dir
        self._district_defs_dir = district_defs_dir
        self._char_defs_dir = char_defs_dir
        self._placement_path = placement_path

    # -- static canon (never mutated, read fresh every build) -----------

    def _load_room_names(self) -> dict[str, str]:
        names = dict(_CIRCULATION_ROOMS)
        if os.path.isdir(self._district_defs_dir):
            for fname in sorted(os.listdir(self._district_defs_dir)):
                if not fname.endswith(".json"):
                    continue
                with open(os.path.join(self._district_defs_dir, fname)) as f:
                    d = json.load(f)
                names[d["id"]] = d["name"]
        return names

    def _load_character_refs(self) -> dict[str, str]:
        """characterId -> agentRef, for every real character."""
        refs = {}
        if os.path.isdir(self._char_defs_dir):
            for fname in sorted(os.listdir(self._char_defs_dir)):
                if not fname.endswith(".json"):
                    continue
                with open(os.path.join(self._char_defs_dir, fname)) as f:
                    c = json.load(f)
                refs[c["id"]] = c["agentRef"]
        return refs

    def _load_home_rooms(self) -> dict[str, str]:
        """characterId -> its Phase W2 `placement.json` roomId (the
        default/home location used when no dynamic activity says
        otherwise)."""
        homes = {}
        data = _load_json(self._placement_path, default=[])
        for p in data:
            homes[p["characterId"]] = p["roomId"]
        return homes

    # -- runtime (Phase W4 output; may be empty/missing) -----------------

    def _load_runtime(self):
        world = _load_json(
            os.path.join(self._runtime_dir, "world.json"),
            default={"engineStatus": "idle", "version": "0.1.0",
                     "timestamp": "", "activeAgents": [], "activeDistricts": []},
        )
        missions = _load_json(os.path.join(self._runtime_dir, "missions.json"), default=[])
        portfolio = _load_json(
            os.path.join(self._runtime_dir, "portfolio.json"),
            default={"positions": [], "timestamp": ""},
        )
        telemetry = _load_json(
            os.path.join(self._runtime_dir, "telemetry.json"),
            default={"metrics": [], "timestamp": ""},
        )
        notifications = _load_json(os.path.join(self._runtime_dir, "notifications.json"), default=[])
        events = _load_json(os.path.join(self._runtime_dir, "events.json"), default=[])
        # Phase W13-1
        orders = _load_json(
            os.path.join(self._runtime_dir, "orders.json"),
            default={"activeCount": 0, "states": [], "timestamp": ""},
        )
        return world, missions, portfolio, telemetry, notifications, events, orders

    # -- build ------------------------------------------------------------

    def build(self, sequence: int = 0) -> WorldState:
        room_names = self._load_room_names()
        agent_refs = self._load_character_refs()
        home_rooms = self._load_home_rooms()
        world, missions_raw, portfolio_raw, telemetry_raw, notifications_raw, events_raw, orders_raw = (
            self._load_runtime()
        )

        active_agent_ids = set(world.get("activeAgents", []))
        active_district_ids = set(world.get("activeDistricts", []))

        missions = tuple(
            MissionState(
                mission_id=str(m["id"]),
                title=str(m["title"]),
                district=str(m["district"]),
                status=str(m["status"]),
                description=str(m.get("description", "")),
            )
            for m in missions_raw
        )

        notifications = tuple(
            NotificationState(
                notification_id=str(n["id"]),
                timestamp=str(n["timestamp"]),
                message=str(n["message"]),
                severity=str(n["severity"]),
                read=bool(n.get("read", False)),
            )
            for n in notifications_raw
        )

        events = tuple(
            EventState(
                event_id=str(e["id"]),
                timestamp=str(e["timestamp"]),
                event_type=str(e["type"]),
                district=str(e["district"]),
                severity=str(e["severity"]),
                agent=str(e.get("agent", "")),
                message=str(e.get("message", "")),
            )
            for e in events_raw
        )

        portfolio = tuple(
            PortfolioState(
                symbol=str(p["symbol"]),
                district=str(p.get("district", "portfolio-garden")),
                size_label=str(p.get("sizeLabel", p.get("size_label", ""))),
            )
            for p in portfolio_raw.get("positions", [])
        )

        # Phase W11 — optional portfolio-wide figures. Absent in the
        # Phase W4 payload shape (no "summary" key) or in any capture
        # where the trading engine didn't supply one this cycle -> None,
        # never a fabricated PortfolioSummaryState of zeros.
        summary_raw = portfolio_raw.get("summary")
        portfolio_summary = (
            PortfolioSummaryState(
                daily_pnl=summary_raw.get("dailyPnl"),
                floating_pnl=summary_raw.get("floatingPnl"),
                drawdown=summary_raw.get("drawdown"),
                win_rate=summary_raw.get("winRate"),
                avg_rr=summary_raw.get("avgRr"),
            )
            if isinstance(summary_raw, dict)
            else None
        )

        telemetry = tuple(
            TelemetryState(
                name=str(t["name"]),
                value=float(t["value"]),
                unit=str(t.get("unit", "")),
                district=str(t.get("district", "")),
            )
            for t in telemetry_raw.get("metrics", [])
        )

        # Phase W13-1 — read-only composite order-timeline rows. Rows
        # missing "symbol" are skipped (same "skip the bad row" rule
        # every other collection in this method follows).
        orders = tuple(
            OrderTimelineState(symbol=str(o["symbol"]), state=o.get("state"))
            for o in orders_raw.get("states", [])
            if "symbol" in o
        )

        # Phase W13-1 — optional reconciliation-wide figures. Absent
        # in the payload (engine hasn't run this capture, or an older
        # orders.json shape) -> None, never a fabricated
        # ReconciliationState of zeros.
        reconciliation_raw = orders_raw.get("reconciliation")
        reconciliation = (
            ReconciliationState(
                last_run=reconciliation_raw.get("lastRun"),
                last_result=reconciliation_raw.get("lastResult"),
                event_count=reconciliation_raw.get("eventCount"),
                suppressed_repeat_count=reconciliation_raw.get("suppressedRepeatCount"),
            )
            if isinstance(reconciliation_raw, dict)
            else None
        )


        # -- agents: every real character, current room = dynamic active
        #    district (best-effort: first active district if the agent
        #    itself is active and any district is flagged active) else its
        #    static Phase W2 home room.
        agents = []
        for agent_id, agent_ref in agent_refs.items():
            is_active = agent_id in active_agent_ids
            home_room = home_rooms.get(agent_id, "lobby")
            current_room = home_room
            agents.append(
                AgentState(
                    agent_id=agent_id,
                    agent_ref=agent_ref,
                    current_room_id=current_room,
                    is_active=is_active,
                    status="working" if is_active else "idle",
                )
            )
        agents = tuple(agents)

        occupants_by_room: dict[str, list[str]] = {rid: [] for rid in room_names}
        for a in agents:
            occupants_by_room.setdefault(a.current_room_id, []).append(a.agent_id)

        missions_by_room: dict[str, list[str]] = {rid: [] for rid in room_names}
        for m in missions:
            missions_by_room.setdefault(m.district, []).append(m.mission_id)

        rooms = tuple(
            RoomState(
                room_id=room_id,
                name=name,
                occupant_agent_ids=tuple(occupants_by_room.get(room_id, [])),
                active_mission_ids=tuple(missions_by_room.get(room_id, [])),
                is_active=room_id in active_district_ids,
            )
            for room_id, name in room_names.items()
        )

        return WorldState(
            engine_status=str(world.get("engineStatus", "idle")),
            version=str(world.get("version", "0.1.0")),
            captured_at=str(world.get("timestamp", "")),
            sequence=sequence,
            rooms=rooms,
            agents=agents,
            missions=missions,
            portfolio=portfolio,
            portfolio_summary=portfolio_summary,
            notifications=notifications,
            events=events,
            telemetry=telemetry,
            orders=orders,
            reconciliation=reconciliation,
        )
