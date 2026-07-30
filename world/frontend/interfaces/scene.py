"""SceneRenderer — the rendering behavior contract for a `Scene`
(the data class describing what a scene contains lives in
`world.frontend.scene.scene.Scene`, not here — this module only
covers *behavior*, per the interfaces/data split used across this
package)."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.scene.scene import Scene


class SceneRenderer(ABC):
    """Contract for displaying one `Scene` (one room/department, its
    layers, and the characters currently placed in it)."""

    @abstractmethod
    def enter(self, scene: "Scene") -> None:
        """Called once when a scene becomes active (e.g. camera
        transitions into a room)."""
        raise NotImplementedError

    @abstractmethod
    def exit(self, scene: "Scene") -> None:
        """Called once when a scene is unloaded (e.g. camera leaves
        the room). Must release any per-scene resources."""
        raise NotImplementedError

    @abstractmethod
    def update(self, scene: "Scene", delta_seconds: float) -> None:
        """Advance per-scene state (layer ordering, character
        placement) by `delta_seconds`. No trading logic — purely
        presentational timing."""
        raise NotImplementedError
