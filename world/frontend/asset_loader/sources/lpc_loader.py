"""Liberated Pixel Cup (LPC)-backed AssetLoader — see
`base.ManifestBackedAssetLoader`. This is the source for every character
sprite in `world/data/assets/asset_manifest.json` (category
`character-sprite`), matching `world/docs/asset-conventions.md`."""

from world.frontend.asset_loader.asset_registry import AssetSource
from world.frontend.asset_loader.sources.base import ManifestBackedAssetLoader


class LPCLoader(ManifestBackedAssetLoader):
    SOURCE = AssetSource.LPC
