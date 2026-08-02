"""SelectionManager — Selection System.

Validates a selection target against real ids before accepting it: rooms/
departments and characters against `world.runtime.api` (Phase W5),
furniture/decoration instances against `world/data/assets/room_assets.json`
(Phase W6's per-room placement data — each entry's `instanceId` is exactly
the addressable id a click/tap event would carry), and events against the
current `world.simulation.api.get_current_events()` (Phase W7). Simulation
events are transient — they only exist in whatever tick's `SimulationState`
produced them — so "select an event" only succeeds if it's still current
or, given a `timeline_controller.TimelineController`, appears in retained
history; see `select_event`.

Load-once, injectable, same pattern as `world.simulation.engine.
SimulationEngine._load_spatial`: `room_assets.json` doesn't change at
runtime, so reading it once at construction (not per `select()` call)
avoids repeated disk I/O for a per-click operation.
"""

import json
import os

from world.interaction.models import SELECTION_KINDS, Selection
from world.runtime import api as runtime_api
from world.simulation import api as simulation_api

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_THIS_DIR)
DEFAULT_ROOM_ASSETS_PATH = os.path.join(WORLD_ROOT, "data", "assets", "room_assets.json")


def _load_room_assets(path: str) -> dict[str, dict]:
    """room_id -> that room's raw `room_assets.json` entry."""
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        rows = json.load(f)
    return {row["roomId"]: row for row in rows}


def _placement_ids(room_assets: dict[str, dict]) -> set[str]:
    ids: set[str] = set()
    for row in room_assets.values():
        for placement in row.get("furniturePlacements", []):
            ids.add(placement["instanceId"])
        for placement in row.get("decorationPlacements", []):
            ids.add(placement["instanceId"])
    return ids


class UnknownSelectionTargetError(ValueError):
    """Raised when `select()` is given an id that doesn't resolve against
    any real data source for its `kind`."""


class SelectionManager:
    def __init__(
        self,
        room_assets_path: str = DEFAULT_ROOM_ASSETS_PATH,
        get_world_state=runtime_api.get_world_state,
        get_current_events=simulation_api.get_current_events,
    ) -> None:
        self._room_assets = _load_room_assets(room_assets_path)
        self._placement_ids = _placement_ids(self._room_assets)
        self._get_world_state = get_world_state
        self._get_current_events = get_current_events
        self._current: Selection | None = None

    def select(self, kind: str, target_id: str) -> Selection:
        if kind not in SELECTION_KINDS:
            raise ValueError(f"unknown selection kind {kind!r}; must be one of {SELECTION_KINDS}")
        if not self._resolves(kind, target_id):
            raise UnknownSelectionTargetError(f"no {kind} with id {target_id!r}")
        self._current = Selection(kind=kind, target_id=target_id)
        return self._current

    def clear(self) -> None:
        self._current = None

    @property
    def current(self) -> Selection | None:
        return self._current

    def _resolves(self, kind: str, target_id: str) -> bool:
        if kind in ("room", "department"):
            return self._room_exists(target_id)
        if kind == "character":
            return any(a.agent_id == target_id for a in self._get_world_state().agents)
        if kind in ("furniture", "decoration"):
            return target_id in self._placement_ids
        if kind == "event":
            return any(e.event_id == target_id for e in self._get_current_events())
        return False

    def _room_exists(self, room_id: str) -> bool:
        state = self._get_world_state()
        return any(r.room_id == room_id for r in state.rooms)
