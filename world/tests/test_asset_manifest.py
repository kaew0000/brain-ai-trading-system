"""Phase W6: asset_manifest.json schema validation."""
import json
import os

import jsonschema

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")


def _load(path):
    with open(path) as f:
        return json.load(f)


def test_asset_manifest_matches_schema():
    schema = _load(os.path.join(SCHEMAS_DIR, "asset_manifest.schema.json"))
    manifest = _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))
    jsonschema.validate(instance=manifest, schema=schema)


def test_asset_manifest_covers_all_character_animation_states():
    manifest = _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))
    char_defs_dir = os.path.join(WORLD_ROOT, "characters", "definitions")
    char_ids = [
        _load(os.path.join(char_defs_dir, f))["id"]
        for f in os.listdir(char_defs_dir) if f.endswith(".json")
    ]
    manifest_ids = {e["id"] for e in manifest}
    anims = ["idle", "walking", "working", "celebration", "emergency"]
    for cid in char_ids:
        for anim in anims:
            assert f"sprite.{cid}.{anim}" in manifest_ids


def test_asset_manifest_categories_are_valid():
    manifest = _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))
    for entry in manifest:
        assert entry["category"] in {"character-sprite", "furniture", "decoration"}
        assert entry["source"] in {"opengameart", "lpc", "kenney", "custom"}
