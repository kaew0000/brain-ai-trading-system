"""Phase W6: every new schema file is valid JSON Schema, and every new data
file that has a same-named schema validates against it. Mirrors the
existing `test_schema_integrity.py` (Phase W1) / `test_office_layout_schema.py`
(Phase W2) pattern for this phase's files."""
import json
import os

import jsonschema

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")
INTERACTIONS_DIR = os.path.join(WORLD_ROOT, "data", "interactions")
CHARACTERS_DATA_DIR = os.path.join(WORLD_ROOT, "data", "characters")

W6_SCHEMA_TO_DATA = {
    "asset_manifest.schema.json": os.path.join(ASSETS_DIR, "asset_manifest.json"),
    "character_assets.schema.json": os.path.join(ASSETS_DIR, "character_assets.json"),
    "furniture_assets.schema.json": os.path.join(ASSETS_DIR, "furniture_assets.json"),
    "decoration_assets.schema.json": os.path.join(ASSETS_DIR, "decoration_assets.json"),
    "room_assets.schema.json": os.path.join(ASSETS_DIR, "room_assets.json"),
    "asset_packs.schema.json": os.path.join(ASSETS_DIR, "asset_packs.json"),
    "interaction_types.schema.json": os.path.join(INTERACTIONS_DIR, "interaction_types.json"),
    "character_spatial_placement.schema.json": os.path.join(
        CHARACTERS_DATA_DIR, "spatial_placement.json"
    ),
}


def _load(path):
    with open(path) as f:
        return json.load(f)


def test_every_w6_schema_file_is_valid_json():
    for schema_name in W6_SCHEMA_TO_DATA:
        _load(os.path.join(SCHEMAS_DIR, schema_name))  # raises on invalid JSON


def test_every_w6_data_file_validates_against_its_schema():
    for schema_name, data_path in W6_SCHEMA_TO_DATA.items():
        schema = _load(os.path.join(SCHEMAS_DIR, schema_name))
        data = _load(data_path)
        jsonschema.validate(instance=data, schema=schema)
