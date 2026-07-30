"""CameraState + ReferenceCameraController.

`ReferenceCameraController` is a concrete implementation of
`world.frontend.interfaces.camera.CameraController` — but it is
*state-only*: it computes what the camera's zoom/pan/focus target
should be, and returns a `CameraState`. It never draws anything. A
real engine binding reads the returned `CameraState` and turns it
into an actual view/projection matrix; that step is still Phase W4+.

This is provided now (rather than left as pure interface) because
focus/follow/center math is renderer-independent and worth getting
right once, tested, and reused by every future concrete renderer."""

from dataclasses import dataclass, replace
from enum import Enum

from world.frontend.interfaces.camera import CameraController

DEFAULT_ZOOM = 1.0
MIN_ZOOM = 0.25
MAX_ZOOM = 4.0


class FocusMode(str, Enum):
    FREE = "free"
    ROOM = "room"
    CHARACTER = "character"
    FOLLOW_CHARACTER = "follow_character"


@dataclass(frozen=True)
class CameraState:
    """Immutable camera state snapshot."""

    x: float = 0.0
    y: float = 0.0
    zoom: float = DEFAULT_ZOOM
    focus_mode: FocusMode = FocusMode.FREE
    focus_target: str | None = None


class ReferenceCameraController(CameraController):
    """Pure-state reference implementation. Requires room positions
    (from `world/data/layout/rooms.json`) and character positions
    (from a `WorldState`) to be supplied at construction time so this
    class never reaches into `world/data/*` or the trading engine
    itself — it stays a pure function of the data it's given."""

    def __init__(self, room_anchors: dict[str, tuple[float, float]]) -> None:
        """`room_anchors`: room_id -> (x, y), typically the
        `cameraAnchor` field of each `world/data/layout/rooms.json`
        entry."""
        self._room_anchors = room_anchors
        self._state = CameraState()
        self._character_positions: dict[str, tuple[float, float]] = {}

    @property
    def state(self) -> CameraState:
        return self._state

    def update_character_position(self, character_id: str, x: float, y: float) -> None:
        """Feed in the latest known position for a character so
        `follow_character` can keep tracking it. Called by whoever
        owns the `WorldState` each update — this class does not fetch
        positions itself."""
        self._character_positions[character_id] = (x, y)
        if self._state.focus_mode == FocusMode.FOLLOW_CHARACTER and self._state.focus_target == character_id:
            self._state = replace(self._state, x=x, y=y)

    def zoom_to(self, level: float) -> CameraState:
        clamped = max(MIN_ZOOM, min(MAX_ZOOM, level))
        self._state = replace(self._state, zoom=clamped)
        return self._state

    def pan_by(self, dx: float, dy: float) -> CameraState:
        self._state = replace(
            self._state,
            x=self._state.x + dx,
            y=self._state.y + dy,
            focus_mode=FocusMode.FREE,
            focus_target=None,
        )
        return self._state

    def focus_room(self, room_id: str) -> CameraState:
        if room_id not in self._room_anchors:
            raise KeyError(f"unknown room_id {room_id!r}")
        x, y = self._room_anchors[room_id]
        self._state = replace(
            self._state, x=x, y=y, focus_mode=FocusMode.ROOM, focus_target=room_id
        )
        return self._state

    def focus_character(self, character_id: str) -> CameraState:
        if character_id not in self._character_positions:
            raise KeyError(f"no known position for character_id {character_id!r}")
        x, y = self._character_positions[character_id]
        self._state = replace(
            self._state, x=x, y=y, focus_mode=FocusMode.CHARACTER, focus_target=character_id
        )
        return self._state

    def follow_character(self, character_id: str) -> CameraState:
        if character_id not in self._character_positions:
            raise KeyError(f"no known position for character_id {character_id!r}")
        x, y = self._character_positions[character_id]
        self._state = replace(
            self._state, x=x, y=y, focus_mode=FocusMode.FOLLOW_CHARACTER, focus_target=character_id
        )
        return self._state

    def center_room(self, room_id: str) -> CameraState:
        if room_id not in self._room_anchors:
            raise KeyError(f"unknown room_id {room_id!r}")
        x, y = self._room_anchors[room_id]
        # unlike focus_room, center_room does not change zoom or
        # focus_mode/focus_target — it only recenters position
        self._state = replace(self._state, x=x, y=y)
        return self._state
