"""Phase W6: every existing character has asset + spatial placement data,
and none of it invents a character that doesn't exist."""
import json
import os

import jsonschema

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")
CHAR_DEFS_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")
SPATIAL_PATH = os.path.join(WORLD_ROOT, "data", "characters", "spatial_placement.json")
PLACEMENT_PATH = os.path.join(WORLD_ROOT, "data", "characters", "placement.json")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _real_character_ids():
    return {
        _load(os.path.join(CHAR_DEFS_DIR, f))["id"]
        for f in os.listdir(CHAR_DEFS_DIR) if f.endswith(".json")
    }


def test_character_assets_matches_schema():
    schema = _load(os.path.join(SCHEMAS_DIR, "character_assets.schema.json"))
    character_assets = _load(os.path.join(ASSETS_DIR, "character_assets.json"))
    jsonschema.validate(instance=character_assets, schema=schema)


def test_spatial_placement_matches_schema():
    schema = _load(os.path.join(SCHEMAS_DIR, "character_spatial_placement.schema.json"))
    spatial = _load(SPATIAL_PATH)
    jsonschema.validate(instance=spatial, schema=schema)


def test_every_character_has_exactly_one_asset_entry():
    real_ids = _real_character_ids()
    ca_ids = [c["characterId"] for c in _load(os.path.join(ASSETS_DIR, "character_assets.json"))]
    assert set(ca_ids) == real_ids
    assert len(ca_ids) == len(set(ca_ids))


def test_every_character_has_exactly_one_spatial_entry():
    real_ids = _real_character_ids()
    sp_ids = [s["characterId"] for s in _load(SPATIAL_PATH)]
    assert set(sp_ids) == real_ids
    assert len(sp_ids) == len(set(sp_ids))


def test_spatial_placement_default_room_matches_existing_w2_placement():
    """The additive Phase W6 layer must agree with, not contradict, the
    Phase W2 `placement.json` roomId for every character."""
    placement_by_id = {p["characterId"]: p for p in _load(PLACEMENT_PATH)}
    for s in _load(SPATIAL_PATH):
        assert s["defaultRoom"] == placement_by_id[s["characterId"]]["roomId"]


def test_interaction_radius_is_positive():
    for s in _load(SPATIAL_PATH):
        assert s["interactionRadius"] > 0
