"""Concrete `AssetLoader` implementations, one per `AssetSource` — Phase W6
asset pipeline activation. All four are manifest-metadata-backed (see
`base.ManifestBackedAssetLoader`); none load binary sprite/tile/audio data,
since none exists in this repository yet. Use
`world.frontend.asset_loader.registry_factory.build_default_registry` to get
an `AssetRegistry` with all four wired in."""

from world.frontend.asset_loader.sources.custom_loader import CustomLoader
from world.frontend.asset_loader.sources.kenney_loader import KenneyLoader
from world.frontend.asset_loader.sources.lpc_loader import LPCLoader
from world.frontend.asset_loader.sources.opengameart_loader import OpenGameArtLoader

__all__ = ["OpenGameArtLoader", "LPCLoader", "KenneyLoader", "CustomLoader"]
