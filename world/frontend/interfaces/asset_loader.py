"""AssetLoader — the pluggable-source contract behind AssetRegistry.
One concrete `AssetLoader` implementation per source (OpenGameArt,
LPC, Kenney, a future custom pipeline) — `AssetRegistry`
(`world.frontend.asset_loader.asset_registry`) holds a mapping of
`AssetSource -> AssetLoader` so adding a new source never requires
changing `AssetRegistry` or any renderer code."""

from abc import ABC, abstractmethod
from typing import Any


class AssetLoader(ABC):
    """Contract for loading one asset (a sprite sheet, tileset, or
    audio file) from a specific source into an engine-native handle.
    No source is implemented in Phase W3 — this is the interface new
    loaders (Phase W5, asset pipeline activation) will implement."""

    @abstractmethod
    def can_load(self, asset_id: str) -> bool:
        """Return whether this loader recognizes the given asset id."""
        raise NotImplementedError

    @abstractmethod
    def load(self, asset_id: str) -> Any:
        """Load and return an engine-native handle for the asset.
        The return type is intentionally `Any` — it is whatever the
        concrete renderer's asset representation is."""
        raise NotImplementedError
