"""Asset versioning / compatibility layer (Phase W6).

Every `world/data/assets/asset_manifest.json` entry carries a `version`
(semver string) and a `compatibleWith` list of renderer-engine identifiers.
This module is the one place that interprets `compatibleWith` so no future
renderer integration needs to re-derive the rule."""

from typing import Any

#: Canonical engine identifiers usable in an asset manifest entry's
#: `compatibleWith` list. Kept in sync with the "Future Compatibility"
#: requirement in `world/WORLD.md` (React, PixiJS, Phaser, Godot, Unity).
KNOWN_ENGINES = frozenset({"react", "pixijs", "phaser", "godot", "unity"})


def is_compatible(entry: dict[str, Any], target_engine: str) -> bool:
    """Return whether a manifest entry declares support for `target_engine`.
    An entry with an empty or missing `compatibleWith` list is treated as
    universally compatible (metadata-only assets impose no engine
    constraint until a real renderer implementation says otherwise)."""
    compatible_with = entry.get("compatibleWith") or []
    if not compatible_with:
        return True
    return target_engine in compatible_with


def unknown_engines(entry: dict[str, Any]) -> list[str]:
    """Return any `compatibleWith` values that aren't in `KNOWN_ENGINES`,
    for validation tooling to flag typos early."""
    return [e for e in entry.get("compatibleWith") or [] if e not in KNOWN_ENGINES]
