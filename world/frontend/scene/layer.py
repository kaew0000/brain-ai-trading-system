"""Layer — an ordered group of sprites/tiles drawn together. The
seven standard layer types below are the required draw-order set."""

from dataclasses import dataclass, field
from enum import Enum


class LayerType(str, Enum):
    """The seven standard layers, in required back-to-front draw
    order (the `z_order` on each `Layer` should follow this same
    ordering by convention, but is not enforced by the enum)."""

    BACKGROUND = "background"
    FLOOR = "floor"
    FURNITURE = "furniture"
    CHARACTERS = "characters"
    EFFECTS = "effects"
    UI_OVERLAY = "ui_overlay"
    NOTIFICATION = "notification"


#: Canonical back-to-front draw order for the standard layer set.
STANDARD_LAYER_ORDER: tuple[LayerType, ...] = (
    LayerType.BACKGROUND,
    LayerType.FLOOR,
    LayerType.FURNITURE,
    LayerType.CHARACTERS,
    LayerType.EFFECTS,
    LayerType.UI_OVERLAY,
    LayerType.NOTIFICATION,
)


@dataclass
class Layer:
    """One layer's content. `entity_ids` holds sprite/tile ids that a
    concrete `LayerRenderer` resolves and draws in order; this class
    does not store the sprites/tiles themselves."""

    layer_type: LayerType
    z_order: int
    entity_ids: list[str] = field(default_factory=list)
    visible: bool = True
