"""ViewportState + reference world<->screen coordinate math.

The math here is intentionally trivial (uniform scale + offset) — it
exists so every future concrete `ViewportRenderer` shares one tested
definition of "world_to_screen" instead of five slightly different
ones. A real engine binding may still need its own transform for
things this simple model does not cover (rotation, non-uniform scale);
that is expected and fine."""

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewportState:
    width: int
    height: int
    scale: float = 32.0  # pixels per abstract office unit, placeholder default
    origin_x: float = 0.0
    origin_y: float = 0.0


def world_to_screen(viewport: ViewportState, camera_x: float, camera_y: float, world_x: float, world_y: float) -> tuple[float, float]:
    """Reference implementation matching
    `ViewportRenderer.world_to_screen`. Centers the camera position in
    the viewport."""
    screen_x = (world_x - camera_x) * viewport.scale + viewport.width / 2 + viewport.origin_x
    screen_y = (world_y - camera_y) * viewport.scale + viewport.height / 2 + viewport.origin_y
    return screen_x, screen_y


def screen_to_world(viewport: ViewportState, camera_x: float, camera_y: float, screen_x: float, screen_y: float) -> tuple[float, float]:
    """Inverse of `world_to_screen`."""
    world_x = (screen_x - viewport.width / 2 - viewport.origin_x) / viewport.scale + camera_x
    world_y = (screen_y - viewport.height / 2 - viewport.origin_y) / viewport.scale + camera_y
    return world_x, world_y
