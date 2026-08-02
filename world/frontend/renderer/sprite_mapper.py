"""SpriteMapper — Phase W8.

Resolves `(character_id, behavior)` to a concrete
`world/data/assets/asset_manifest.json` asset id.

Root-cause note (see also `render_config.BEHAVIOR_TO_ANIMATION_STATE`):
there are *two* per-character animation-id sources in this repository
and they disagree.

1. `world/characters/definitions/<id>.json` -> `spriteMeta.animations`
   (Phase W1/W2). Values like `"bastion_idle"` — an underscore id that
   does not appear anywhere in
   `world/data/assets/asset_manifest.json`.
2. `world/data/assets/character_assets.json` -> `spriteAssetIds`
   (Phase W6, asset pipeline activation). Values like
   `"sprite.bastion.idle"` — verified (this phase) to match a real
   `asset_manifest.json` entry for all 16 characters x 5 states.

`SpriteMapper` uses source 2 (`character_assets.json`) exclusively —
it is the newer, pipeline-activated source and the only one that
actually resolves. Source 1 is left untouched (Phase W2 data,
out of this phase's scope) but is no longer the thing a renderer
should read for sprite ids.
"""

import json
import os
from typing import Any

from world.frontend.renderer.render_config import BEHAVIOR_TO_ANIMATION_STATE

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))  # world/frontend/renderer
_WORLD_DIR = os.path.dirname(os.path.dirname(_THIS_DIR))  # world/
_DEFAULT_CHARACTER_ASSETS_PATH = os.path.join(_WORLD_DIR, "data", "assets", "character_assets.json")


class UnknownCharacterError(LookupError):
    """Raised when `character_id` has no `character_assets.json` entry."""


def load_character_assets(path: str = _DEFAULT_CHARACTER_ASSETS_PATH) -> dict[str, dict[str, str]]:
    """Return `{character_id: {animation_state: asset_id}}`, read fresh
    from `character_assets.json`. Returns `{}` rather than raising if
    the file is missing, matching the fail-soft convention used by
    every other Phase W6 data reader in this package."""
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        entries: list[dict[str, Any]] = json.load(f)
    return {entry["characterId"]: dict(entry["spriteAssetIds"]) for entry in entries}


class SpriteMapper:
    """Behaviour -> sprite asset id resolution for one asset registry.

    Construction reads `character_assets.json` once; call
    `refresh()` if the file changes underneath a long-lived instance
    (mirrors `AssetRegistry.clear_cache`'s explicit-refresh style
    rather than re-reading the file on every lookup).
    """

    def __init__(self, character_assets_path: str = _DEFAULT_CHARACTER_ASSETS_PATH) -> None:
        self._path = character_assets_path
        self._by_character = load_character_assets(character_assets_path)

    def refresh(self) -> None:
        self._by_character = load_character_assets(self._path)

    def known_character_ids(self) -> list[str]:
        return list(self._by_character.keys())

    def animation_state_for(self, behavior: str) -> str:
        """Map a `world.simulation.models.CHARACTER_BEHAVIORS` label to
        one of the five animation states every character actually has
        sprites for. See `render_config.BEHAVIOR_TO_ANIMATION_STATE`
        for the documented fallback rationale."""
        try:
            return BEHAVIOR_TO_ANIMATION_STATE[behavior]
        except KeyError as exc:
            raise ValueError(
                f"unrecognized behavior {behavior!r}; expected one of "
                f"{sorted(BEHAVIOR_TO_ANIMATION_STATE)}"
            ) from exc

    def asset_id_for(self, character_id: str, behavior: str) -> str:
        """Return the `asset_manifest.json` id for this character's
        sprite in the given behaviour state (after animation-state
        fallback). Raises `UnknownCharacterError` if `character_id`
        has no `character_assets.json` entry."""
        try:
            states = self._by_character[character_id]
        except KeyError as exc:
            raise UnknownCharacterError(
                f"no character_assets.json entry for character_id {character_id!r}"
            ) from exc
        animation_state = self.animation_state_for(behavior)
        try:
            return states[animation_state]
        except KeyError as exc:
            raise UnknownCharacterError(
                f"character {character_id!r} has no {animation_state!r} sprite "
                f"(available: {sorted(states)})"
            ) from exc
