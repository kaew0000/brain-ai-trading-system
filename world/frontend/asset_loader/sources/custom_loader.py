"""Custom (Brain AI-specific, non-third-party) AssetLoader — see
`base.ManifestBackedAssetLoader`."""

from world.frontend.asset_loader.asset_registry import AssetSource
from world.frontend.asset_loader.sources.base import ManifestBackedAssetLoader


class CustomLoader(ManifestBackedAssetLoader):
    SOURCE = AssetSource.CUSTOM
