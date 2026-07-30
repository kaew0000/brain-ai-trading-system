"""SpriteRenderer — abstraction only. Draws a
`world.frontend.asset_loader.sprite.Sprite` value object; no drawing
implementation lives in this repository."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.asset_loader.sprite import Sprite


class SpriteRenderer(ABC):
    """Contract for drawing a single sprite instance."""

    @abstractmethod
    def draw(self, sprite: "Sprite") -> None:
        """Draw one sprite at its current position/equipment/animation
        frame. Implementations must not mutate `sprite`."""
        raise NotImplementedError
