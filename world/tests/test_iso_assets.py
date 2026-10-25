"""Phase W-ISO-2: isometric asset pipeline contract.

Pins the generator's determinism, that committed PNGs/manifests match the
spec, and that the backend catalog covers every state a behaviour can map to.
"""

import json
import os

import struct

import pytest

from world.frontend.renderer.render_config import BEHAVIOR_TO_ANIMATION_STATE
from world.scripts import generate_iso_assets as gen
from world.simulation.models import CHARACTER_BEHAVIORS


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _png_size(path):
    """Read width/height from the PNG IHDR chunk (no Pillow needed)."""
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


def test_generated_files_are_up_to_date():
    pytest.importorskip("PIL")
    """Re-running the generator must be a no-op on a clean checkout."""
    stale = [
        p for p, data in gen.build_outputs().items()
        if not os.path.isfile(p) or open(p, "rb").read() != data
    ]
    assert stale == [], f"run `python -m world.scripts.generate_iso_assets`: {stale}"


def test_generator_is_deterministic():
    pytest.importorskip("PIL")
    assert gen.build_outputs() == gen.build_outputs()


def test_png_sizes_match_manifest_iso_block():
    iso = _load(gen.FRONTEND_MANIFEST)["iso"]
    for key, e in iso["props"].items():
        assert _png_size(os.path.join(gen.ISO_DIR, "props", f"{key}.png")) == (e["width"], e["height"])
    cfg = iso["character"]
    for cid in iso["npc"]:
        expected = (cfg["frameWidth"] * len(cfg["poses"]), cfg["frameHeight"])
        assert _png_size(os.path.join(gen.ISO_DIR, "npc", f"{cid}.png")) == expected


def test_every_behavior_resolves_to_a_character_sprite_and_an_iso_pose():
    iso = _load(gen.FRONTEND_MANIFEST)["iso"]
    for behavior in CHARACTER_BEHAVIORS:
        assert BEHAVIOR_TO_ANIMATION_STATE[behavior] == behavior  # identity after W-ISO-2
        assert iso["character"]["behaviorPose"][behavior] in iso["character"]["poses"]


def test_backend_catalog_has_new_states_for_all_characters():
    manifest_ids = {e["id"] for e in _load(os.path.join(gen.DATA_DIR, "asset_manifest.json"))}
    for entry in _load(os.path.join(gen.DATA_DIR, "character_assets.json")):
        for state in ("meeting", "resting", "working-seated"):
            aid = entry["spriteAssetIds"][state]
            assert aid == f"sprite.{entry['characterId']}.{state}"
            assert aid in manifest_ids


def test_iso_assets_do_not_change_orthographic_room_placements():
    """New furniture is catalogued only; no room placement references it yet."""
    rooms = open(os.path.join(gen.DATA_DIR, "room_assets.json"), encoding="utf-8").read()
    for new_id in ("furniture.partition-low", "furniture.partition-full", "furniture.sofa"):
        assert new_id not in rooms
