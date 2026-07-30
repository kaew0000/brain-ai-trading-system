"""TileRenderer — abstraction only. Draws a
`world.frontend.asset_loader.tile.Tile` value object (one cell of a
floor/background layer); no drawing implementation here."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.asset_loader.tile import Tile


class TileRenderer(ABC):
    """Contract for drawing a single tile instance."""

    @abstractmethod
    def draw(self, tile: "Tile") -> None:
        """Draw one tile at its grid position. Implementations must
        not mutate `tile`."""
        raise NotImplementedError
