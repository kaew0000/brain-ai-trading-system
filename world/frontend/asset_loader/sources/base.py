"""ManifestBackedAssetLoader — shared implementation behind every concrete
Phase W6 `AssetLoader`.

Per `world/docs/architecture/../roadmap.md`, Phase W6 activates the asset
pipeline design left by Phase W3 (`world/frontend/interfaces/asset_loader.py`,
`world/frontend/asset_loader/asset_registry.py`). No renderer exists yet and
no binary sprite/tile/audio files ship in this repository, so a loader's
"engine-native handle" is, for now, the asset's own manifest metadata entry
(`dict`) read from `world/data/assets/asset_manifest.json` — everything a
future concrete renderer needs to know to actually fetch and draw the asset
(source, tags, variants, dependencies, version, compatible engines). This
keeps the pipeline fully engine-neutral and testable without inventing pixel
data that doesn't exist.
"""

import json
import os
from typing import Any

from world.frontend.asset_loader.asset_registry import AssetSource
from world.frontend.interfaces.asset_loader import AssetLoader

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/asset_loader/sources
_WORLD_DIR = os.path.dirname(os.path.dirname(os.path.dirname(_THIS_DIR)))  # world/
_DEFAULT_MANIFEST_PATH = os.path.join(_WORLD_DIR, "data", "assets", "asset_manifest.json")


def load_manifest(manifest_path: str = _DEFAULT_MANIFEST_PATH) -> list[dict]:
    """Read `asset_manifest.json` fresh from disk. Returns an empty list
    rather than raising if the file is missing, so importing this module
    never fails outside a full repo checkout."""
    if not os.path.isfile(manifest_path):
        return []
    with open(manifest_path) as f:
        return json.load(f)


class ManifestBackedAssetLoader(AssetLoader):
    """Concrete `AssetLoader` for one `AssetSource`. Subclasses only need to
    set the `SOURCE` class attribute — `can_load`/`load` are implemented
    once here against the shared manifest."""

    SOURCE: AssetSource

    def __init__(self, manifest_path: str = _DEFAULT_MANIFEST_PATH) -> None:
        self._entries_by_id = {
            entry["id"]: entry
            for entry in load_manifest(manifest_path)
            if entry.get("source") == self.SOURCE.value
        }

    def can_load(self, asset_id: str) -> bool:
        return asset_id in self._entries_by_id

    def load(self, asset_id: str) -> Any:
        try:
            return self._entries_by_id[asset_id]
        except KeyError as exc:
            raise KeyError(
                f"{type(self).__name__} cannot load {asset_id!r}: "
                f"not a registered {self.SOURCE.value} asset"
            ) from exc
