"""ViewportState + reference world<->screen coordinate math.

The math here is intentionally trivial (uniform scale + offset) — it
exists so every future concrete `ViewportRenderer` shares one tested
definition of "world_to_screen" instead of five slightly different
ones. A real engine binding may still need its own transform for
things this simple model does not cover (rotation, non-uniform scale);
that is expected and fine."""

from dataclasses import dataclass

#: Projection identifiers. `orthographic` is the original top-down
#: uniform-scale mapping and stays the default so every existing caller
#: behaves exactly as before. `isometric` is a 2:1 dimetric view (Phase
#: W-ISO-1): world +x runs down-right, world +y runs down-left.
PROJECTION_ORTHOGRAPHIC = "orthographic"
PROJECTION_ISOMETRIC = "isometric"
SUPPORTED_PROJECTIONS = (PROJECTION_ORTHOGRAPHIC, PROJECTION_ISOMETRIC)

#: Vertical squash of the isometric view: half-tile height divided by
#: half-tile width. 0.5 gives the classic 2:1 pixel-art diamond.
DEFAULT_ISO_TILE_RATIO = 0.5


@dataclass(frozen=True)
class ViewportState:
    width: int
    height: int
    scale: float = 32.0  # pixels per abstract office unit, placeholder default
    origin_x: float = 0.0
    origin_y: float = 0.0
    projection: str = PROJECTION_ORTHOGRAPHIC
    iso_tile_ratio: float = DEFAULT_ISO_TILE_RATIO

    def __post_init__(self) -> None:
        if self.projection not in SUPPORTED_PROJECTIONS:
            raise ValueError(
                f"unsupported projection {self.projection!r}; expected one of {SUPPORTED_PROJECTIONS}"
            )
        if self.iso_tile_ratio <= 0:
            raise ValueError("iso_tile_ratio must be > 0")


def world_to_screen(viewport: ViewportState, camera_x: float, camera_y: float, world_x: float, world_y: float) -> tuple[float, float]:
    """Reference implementation matching
    `ViewportRenderer.world_to_screen`. Centers the camera position in
    the viewport. Honors `viewport.projection`."""
    if viewport.projection == PROJECTION_ISOMETRIC:
        dx = world_x - camera_x
        dy = world_y - camera_y
        iso_x = (dx - dy) * viewport.scale + viewport.width / 2 + viewport.origin_x
        iso_y = (dx + dy) * viewport.scale * viewport.iso_tile_ratio + viewport.height / 2 + viewport.origin_y
        return iso_x, iso_y
    screen_x = (world_x - camera_x) * viewport.scale + viewport.width / 2 + viewport.origin_x
    screen_y = (world_y - camera_y) * viewport.scale + viewport.height / 2 + viewport.origin_y
    return screen_x, screen_y


def screen_to_world(viewport: ViewportState, camera_x: float, camera_y: float, screen_x: float, screen_y: float) -> tuple[float, float]:
    """Inverse of `world_to_screen`."""
    if viewport.projection == PROJECTION_ISOMETRIC:
        a = (screen_x - viewport.width / 2 - viewport.origin_x) / viewport.scale  # dx - dy
        b = (screen_y - viewport.height / 2 - viewport.origin_y) / (viewport.scale * viewport.iso_tile_ratio)  # dx + dy
        return (a + b) / 2 + camera_x, (b - a) / 2 + camera_y
    world_x = (screen_x - viewport.width / 2 - viewport.origin_x) / viewport.scale + camera_x
    world_y = (screen_y - viewport.height / 2 - viewport.origin_y) / viewport.scale + camera_y
    return world_x, world_y
