"""Kenney-backed AssetLoader — see `base.ManifestBackedAssetLoader`."""

from world.frontend.asset_loader.asset_registry import AssetSource
from world.frontend.asset_loader.sources.base import ManifestBackedAssetLoader


class KenneyLoader(ManifestBackedAssetLoader):
    SOURCE = AssetSource.KENNEY
