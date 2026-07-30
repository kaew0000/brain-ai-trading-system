"""LayerRenderer — abstraction only. Draws one
`world.frontend.scene.layer.Layer` (an ordered group of
sprites/tiles) in back-to-front order; no drawing implementation
here."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.scene.layer import Layer


class LayerRenderer(ABC):
    """Contract for drawing one layer. A concrete `Renderer` calls
    this once per `LayerType`, in ascending `z_order`."""

    @abstractmethod
    def draw_layer(self, layer: "Layer") -> None:
        """Draw every sprite/tile registered on this layer, in this
        layer's internal order."""
        raise NotImplementedError
