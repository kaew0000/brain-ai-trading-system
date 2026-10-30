"""V16 §93: LPC character import - spec, committed assets and the importer's unsupported-garment detection."""
from __future__ import annotations

import csv
import json
import os

import pytest
from PIL import Image

from world.scripts import import_lpc_characters as imp

FRONTEND = os.path.join(imp.REPO_ROOT, "dashboard_src", "public", "assets", "world")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def spec():
    return _load(imp.SPEC_PATH)


@pytest.fixture(scope="module")
def manifest():
    return _load(os.path.join(FRONTEND, "manifest.json"))


def test_spec_rows_fit_the_sheet(spec):
    for name, anim in spec["animations"].items():
        last = anim["row"] + (len(spec["directions"]) - 1 if anim["directional"] else 0)
        assert last < spec["rows"], name
        assert anim["startFrame"] + anim["frames"] <= spec["columns"], name
    assert spec["fallbackAnimation"] in spec["animations"]
    assert set(spec["behaviorAnimation"].values()) <= set(spec["animations"])


def test_every_role_maps_to_a_known_npc_role(spec, manifest):
    assert set(spec["sourceFolders"].values()) <= set(manifest["npc"])
    assert len(set(spec["sourceFolders"].values())) == len(spec["sourceFolders"])


def test_committed_sheets_exist_with_expected_size(spec, manifest):
    want = (spec["columns"] * spec["frameSize"], spec["rows"] * spec["frameSize"])
    lpc = manifest["lpc"]
    assert set(lpc["sheets"]) == set(spec["sourceFolders"].values())
    for role, url in lpc["sheets"].items():
        path = os.path.join(FRONTEND, url.removeprefix("/assets/world/"))
        with Image.open(path) as im:
            assert im.size == want, role


def test_manifest_block_matches_spec_and_other_keys_survive(spec, manifest):
    block = manifest["lpc"]
    for key, value in spec.items():
        if key != "sourceFolders":
            assert block[key] == value, key
    assert {"iso", "npc", "buildings", "props"} <= set(manifest)


def test_credits_file_is_committed_and_deduplicated():
    with open(imp.CREDITS_PATH, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    assert rows and list(rows[0]) == imp.CREDITS_HEADER
    names = [r["filename"] for r in rows]
    assert len(names) == len(set(names))


def test_unsupported_animations_are_derived_from_layer_support(spec):
    selection = {
        "layers": [
            {"itemId": "body", "supportedAnimations": ["walk", "sit", "emote"]},
            {"itemId": "tunic", "supportedAnimations": ["walk"]},
        ]
    }
    assert imp.unsupported_animations(selection, spec["animations"]) == ["emote", "sit"]
    assert imp.unsupported_animations({"layers": []}, spec["animations"]) == []


def test_build_block_rejects_a_missing_folder(spec, tmp_path):
    with pytest.raises(ValueError, match="missing character folder"):
        imp.build_lpc_block(spec, str(tmp_path))
