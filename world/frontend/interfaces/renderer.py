"""Renderer — the top-level contract a concrete engine binding
(Phaser, PixiJS, Godot, Unity, React Canvas, or anything else) must
implement to display Brain AI Command World.

No implementation lives in this repository yet. Choosing and wiring a
concrete engine is Phase W4 (see `world/docs/roadmap.md`)."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.renderer.world_state import WorldState  # noqa
    from world.frontend.scene.scene import Scene


class Renderer(ABC):
    """Top-level renderer contract. One `Renderer` owns one `Viewport`,
    the current `Scene`, and is driven by a `WorldState` snapshot on
    every frame/update. It never mutates `WorldState` — this is a
    read-only presentation layer."""

    @abstractmethod
    def initialize(self) -> None:
        """Prepare the renderer (create window/canvas/context). Called
        once before the first `load_scene`."""
        raise NotImplementedError

    @abstractmethod
    def load_scene(self, scene: "Scene") -> None:
        """Load and prepare a `Scene` for display. Must not be called
        before `initialize`."""
        raise NotImplementedError

    @abstractmethod
    def render(self, world_state: "WorldState") -> None:  # noqa
        """Render one frame/update using the given read-only
        `WorldState` snapshot against the currently loaded scene."""
        raise NotImplementedError

    @abstractmethod
    def shutdown(self) -> None:
        """Release all renderer resources."""
        raise NotImplementedError
