"""AssetLocator — Phase W8.

The one place a renderer asks "what does this character/piece of
furniture/decoration actually look like" without knowing anything
about `AssetRegistry`, `character_assets.json`, or
`room_assets.json` shapes itself.

Wraps three Phase W6 data sources behind one small read API:

- `world.frontend.asset_loader.registry_factory.build_default_registry`
  (`AssetSource -> AssetLoader`, resolves an asset id to its
  `asset_manifest.json` entry)
- `character_assets.json` via `sprite_mapper.SpriteMapper`
  (character_id + behaviour -> sprite asset id)
- `room_assets.json` (room_id -> furniture/decoration instance
  placements), cross-referenced against `furniture_assets.json` /
  `decoration_assets.json` for each placement's `manifestId`

No drawing, no engine-specific shape — every method returns plain
dicts (the `asset_manifest.json` entry shape) or small dataclasses,
per the read-only, engine-agnostic contract every other
`world/frontend/` module already follows.
"""

import json
import os
from dataclasses import dataclass, field

from world.frontend.asset_loader.asset_registry import AssetRegistry, UnresolvedAssetError
from world.frontend.asset_loader.registry_factory import build_default_registry
from world.frontend.renderer.sprite_mapper import SpriteMapper, UnknownCharacterError

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/renderer
_WORLD_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # world/
_DATA_DIR = os.path.join(_WORLD_DIR, "data", "assets")
_DEFAULT_ROOM_ASSETS_PATH = os.path.join(_DATA_DIR, "room_assets.json")
_DEFAULT_FURNITURE_ASSETS_PATH = os.path.join(_DATA_DIR, "furniture_assets.json")
_DEFAULT_DECORATION_ASSETS_PATH = os.path.join(_DATA_DIR, "decoration_assets.json")


def _load_json_list(path: str) -> list[dict]:
    if not os.path.isfile(path):
        return []
    with open(path) as f:
        return json.load(f)


@dataclass(frozen=True)
class PlacedProp:
    """One furniture or decoration instance placed in a room, resolved
    down to what a renderer needs: where it goes and what asset draws
    it. `kind` is `"furniture"` or `"decoration"`."""

    instance_id: str
    prop_id: str
    kind: str
    asset_id: str
    x: float
    y: float
    interactions: tuple[str, ...] = field(default_factory=tuple)


class AssetLocator:
    """Read-only asset lookup facade for the Phase W8 renderer.

    `registry` defaults to `registry_factory.build_default_registry()`
    (all four Phase W6 loaders against the real
    `asset_manifest.json`); pass an explicit one in tests to avoid
    touching disk, or to test an unresolved-asset path.
    """

    def __init__(
        self,
        registry: AssetRegistry | None = None,
        sprite_mapper: SpriteMapper | None = None,
        room_assets_path: str = _DEFAULT_ROOM_ASSETS_PATH,
        furniture_assets_path: str = _DEFAULT_FURNITURE_ASSETS_PATH,
        decoration_assets_path: str = _DEFAULT_DECORATION_ASSETS_PATH,
    ) -> None:
        self._registry = registry if registry is not None else build_default_registry()
        self._sprite_mapper = sprite_mapper if sprite_mapper is not None else SpriteMapper()

        self._room_placements = {
            entry["roomId"]: entry for entry in _load_json_list(room_assets_path)
        }
        self._furniture_by_id = {
            entry["id"]: entry for entry in _load_json_list(furniture_assets_path)
        }
        self._decoration_by_id = {
            entry["id"]: entry for entry in _load_json_list(decoration_assets_path)
        }

    # -- characters ---------------------------------------------------

    def character_sprite(self, character_id: str, behavior: str) -> dict | None:
        """Return the `asset_manifest.json` entry for this character's
        sprite in the given behaviour state, or `None` if the
        character or the resolved asset id isn't known. Never raises
        for missing data — a renderer should be able to skip an
        unresolvable sprite rather than crash a whole frame over one
        character; callers that need to distinguish "no data" from
        "known but has no sprite" should call `sprite_mapper` methods
        directly.
        """
        try:
            asset_id = self._sprite_mapper.asset_id_for(character_id, behavior)
        except UnknownCharacterError:
            return None
        try:
            return self._registry.resolve(asset_id)
        except UnresolvedAssetError:
            return None

    # -- rooms ----------------------------------------------------------

    def room_props(self, room_id: str) -> list[PlacedProp]:
        """Return every furniture + decoration instance placed in
        `room_id`, each resolved to its manifest asset id. Rooms with
        no `room_assets.json` entry (or unplaced instances referencing
        an unknown furniture/decoration id) yield an empty list rather
        than raising, matching the fail-soft convention used
        throughout this package's data readers."""
        entry = self._room_placements.get(room_id)
        if entry is None:
            return []

        props: list[PlacedProp] = []
        for fp in entry.get("furniturePlacements", []):
            furniture = self._furniture_by_id.get(fp["furnitureId"])
            if furniture is None:
                continue
            props.append(PlacedProp(
                instance_id=fp["instanceId"],
                prop_id=fp["furnitureId"],
                kind="furniture",
                asset_id=furniture["manifestId"],
                x=fp["position"]["x"],
                y=fp["position"]["y"],
                interactions=tuple(fp.get("interactions", [])),
            ))
        for dp in entry.get("decorationPlacements", []):
            decoration = self._decoration_by_id.get(dp["decorationId"])
            if decoration is None:
                continue
            props.append(PlacedProp(
                instance_id=dp["instanceId"],
                prop_id=dp["decorationId"],
                kind="decoration",
                asset_id=decoration["manifestId"],
                x=dp["position"]["x"],
                y=dp["position"]["y"],
                interactions=(),
            ))
        return props

    def known_room_ids(self) -> list[str]:
        return list(self._room_placements.keys())

    @property
    def registry(self) -> AssetRegistry:
        return self._registry
