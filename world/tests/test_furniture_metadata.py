"""Phase W6: furniture_assets.json / decoration_assets.json metadata."""
import json
import os

import jsonschema

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")


def _load(path):
    with open(path) as f:
        return json.load(f)


def test_furniture_assets_matches_schema():
    schema = _load(os.path.join(SCHEMAS_DIR, "furniture_assets.schema.json"))
    furniture = _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))
    jsonschema.validate(instance=furniture, schema=schema)


def test_decoration_assets_matches_schema():
    schema = _load(os.path.join(SCHEMAS_DIR, "decoration_assets.schema.json"))
    decorations = _load(os.path.join(ASSETS_DIR, "decoration_assets.json"))
    jsonschema.validate(instance=decorations, schema=schema)


def test_every_furniture_resolves_into_manifest():
    manifest_ids = {e["id"] for e in _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))}
    furniture = _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))
    for f in furniture:
        assert f["manifestId"] in manifest_ids


def test_every_decoration_resolves_into_manifest():
    manifest_ids = {e["id"] for e in _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))}
    decorations = _load(os.path.join(ASSETS_DIR, "decoration_assets.json"))
    for d in decorations:
        assert d["manifestId"] in manifest_ids


def test_furniture_footprints_are_positive():
    furniture = _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))
    for f in furniture:
        assert f["footprint"]["width"] > 0
        assert f["footprint"]["height"] > 0
