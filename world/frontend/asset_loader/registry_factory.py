"""Convenience factory: build an `AssetRegistry` with all four Phase W6
concrete `AssetLoader`s registered. This is the only place that needs to
know about all four source implementations at once."""

from world.frontend.asset_loader.asset_registry import AssetRegistry, AssetSource
from world.frontend.asset_loader.sources import (
    CustomLoader,
    KenneyLoader,
    LPCLoader,
    OpenGameArtLoader,
)


def build_default_registry() -> AssetRegistry:
    """Return an `AssetRegistry` with the OpenGameArt, LPC, Kenney, and
    Custom loaders registered against `world/data/assets/asset_manifest.json`.
    Adding a fifth source never requires changing this function's callers —
    only this function itself, per the design in
    `world/frontend/asset_loader/asset_registry.py`."""
    registry = AssetRegistry()
    registry.register_loader(AssetSource.OPENGAMEART, OpenGameArtLoader())
    registry.register_loader(AssetSource.LPC, LPCLoader())
    registry.register_loader(AssetSource.KENNEY, KenneyLoader())
    registry.register_loader(AssetSource.CUSTOM, CustomLoader())
    return registry
