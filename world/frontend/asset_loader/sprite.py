"""Sprite — a value object describing one drawable character/object
instance. Pure data; drawing is `SpriteRenderer`'s job."""

from dataclasses import dataclass, field


@dataclass
class Sprite:
    """`equipment` keys must be a subset of the equipment slots
    defined in `world/characters/definitions/*.json`
    (`spriteMeta.equipmentSlots`): `head`, `body`, `tool`,
    `accessory`, `statusGlow` — this class does not validate that
    itself, it's a plain value object."""

    sprite_id: str
    asset_id: str
    x: float
    y: float
    z_order: int = 0
    equipment: dict[str, str] = field(default_factory=dict)
    animation_state: str = "idle"
