"""FocusManager — thin wrapper around `world.frontend.camera.camera.
ReferenceCameraController` for the Command Dispatch verbs the brief names
that are camera-shaped: Focus Room, Follow Character, Center Camera.

`ReferenceCameraController` already implements every one of these
(`focus_room`, `follow_character`, `center_room`) — Phase W8 built it for
exactly this purpose but nothing outside `world.frontend.renderer.
renderer.SceneGraphRenderer` (which owns a private instance) could reach
it. This gives the interaction layer its own controller, loaded from the
same real room-anchor data `SceneGraphRenderer.initialize()` uses, rather
than depending on a live renderer instance existing (the interaction
layer must work against `world.runtime`/`world.simulation` alone, per the
brief's "backend-independent" renderer constraint).

Character positions must be fed in via `update_character_position` before
`focus_character`/`follow_character` will resolve — this class does not
reach into `world.simulation` itself; `command_dispatcher.py` is
responsible for keeping it current from `SimulationState.characters`
immediately before dispatching a camera command.
"""

from world.frontend.camera.camera import CameraState, ReferenceCameraController
from world.frontend.renderer.room_renderer import load_room_anchors


class FocusManager:
    def __init__(self, room_anchors: dict[str, tuple[float, float]] | None = None) -> None:
        self._camera = ReferenceCameraController(room_anchors=room_anchors or load_room_anchors())

    @property
    def state(self) -> CameraState:
        return self._camera.state

    def update_character_position(self, character_id: str, x: float, y: float) -> None:
        self._camera.update_character_position(character_id, x, y)

    def focus_room(self, room_id: str) -> CameraState:
        return self._camera.focus_room(room_id)

    def center_room(self, room_id: str) -> CameraState:
        return self._camera.center_room(room_id)

    def focus_character(self, character_id: str) -> CameraState:
        return self._camera.focus_character(character_id)

    def follow_character(self, character_id: str) -> CameraState:
        return self._camera.follow_character(character_id)

    def pan_by(self, dx: float, dy: float) -> CameraState:
        return self._camera.pan_by(dx, dy)

    def zoom_to(self, level: float) -> CameraState:
        return self._camera.zoom_to(level)
