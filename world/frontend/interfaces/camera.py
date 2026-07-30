"""CameraController — abstraction only, no renderer implementation.
A concrete camera controller (Phase W4+) reads/writes
`world.frontend.camera.camera.CameraState` and a real engine binding
turns that state into an actual view/projection matrix."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.camera.camera import CameraState


class CameraController(ABC):
    """Camera behavior contract: zoom, pan, and four focus modes
    (focus room, focus character, follow character, center room)."""

    @abstractmethod
    def zoom_to(self, level: float) -> "CameraState":
        """Set an absolute zoom level. Implementations should clamp
        to a sane range; this interface does not mandate one."""
        raise NotImplementedError

    @abstractmethod
    def pan_by(self, dx: float, dy: float) -> "CameraState":
        """Pan the camera by a relative offset in abstract office
        units (see `world/data/layout/rooms.json` spawnLocation
        units)."""
        raise NotImplementedError

    @abstractmethod
    def focus_room(self, room_id: str) -> "CameraState":
        """Frame a single room using its `cameraAnchor`
        (`world/data/layout/rooms.json`)."""
        raise NotImplementedError

    @abstractmethod
    def focus_character(self, character_id: str) -> "CameraState":
        """Frame a single character at its current position (one-time
        snap, not continuous tracking — see `follow_character`)."""
        raise NotImplementedError

    @abstractmethod
    def follow_character(self, character_id: str) -> "CameraState":
        """Continuously track a character's position until a
        different focus/follow call is made."""
        raise NotImplementedError

    @abstractmethod
    def center_room(self, room_id: str) -> "CameraState":
        """Center the camera on a room without changing zoom (unlike
        `focus_room`, which also frames the room)."""
        raise NotImplementedError
