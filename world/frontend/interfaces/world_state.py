"""WorldStateProvider — abstraction only. A future read-only ingestion
adapter (Phase W4 — see `world/docs/roadmap.md`) will implement this
to turn real engine output into a
`world.frontend.renderer.world_state.WorldState` snapshot. No
implementation exists yet; Phase W3 ships the shape only."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from world.frontend.renderer.world_state import WorldState


class WorldStateProvider(ABC):
    """Contract for anything that can produce a `WorldState` snapshot
    for the renderer to consume. Strictly read-only — no method on
    this interface may mutate engine state."""

    @abstractmethod
    def get_current_state(self) -> "WorldState":
        """Return the latest available `WorldState` snapshot."""
        raise NotImplementedError
