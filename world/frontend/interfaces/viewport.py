"""ViewportRenderer — abstraction only. A concrete implementation maps
`world.frontend.viewport.viewport.ViewportState` onto whatever surface
the chosen engine provides (an HTML canvas, a native window, etc)."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.viewport.viewport import ViewportState


class ViewportRenderer(ABC):
    """Contract for translating abstract office-unit coordinates into
    the renderer's screen-space coordinates, and back."""

    @abstractmethod
    def resize(self, width: int, height: int) -> "ViewportState":
        """Handle a resize of the underlying surface."""
        raise NotImplementedError

    @abstractmethod
    def world_to_screen(self, x: float, y: float) -> tuple:
        """Convert an abstract office-unit coordinate to screen-space
        pixels, given the current viewport + camera state."""
        raise NotImplementedError

    @abstractmethod
    def screen_to_world(self, screen_x: float, screen_y: float) -> tuple:
        """Inverse of `world_to_screen` — used for click/tap picking."""
        raise NotImplementedError
