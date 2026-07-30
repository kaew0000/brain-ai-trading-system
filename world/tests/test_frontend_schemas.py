"""Phase W3: schema validation for every frontend config schema, plus
the two Phase W1 schemas (scene-manifest, minimap) that shipped
without a sample/test until now."""

import json
import os

import jsonschema

from world.frontend.scene.scene import Scene

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_SCHEMAS = os.path.join(WORLD_ROOT, "frontend", "schemas")
FRONTEND_SAMPLES = os.path.join(WORLD_ROOT, "frontend", "samples")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _validate(schema_name, sample_name):
    schema = _load(os.path.join(FRONTEND_SCHEMAS, schema_name))
    sample = _load(os.path.join(FRONTEND_SAMPLES, sample_name))
    jsonschema.validate(instance=sample, schema=schema)


def test_renderer_config_schema():
    _validate("renderer_config.schema.json", "renderer_config.sample.json")


def test_camera_config_schema():
    _validate("camera_config.schema.json", "camera_config.sample.json")


def test_layer_config_schema():
    _validate("layer_config.schema.json", "layer_config.sample.json")


def test_asset_registry_config_schema():
    _validate("asset_registry_config.schema.json", "asset_registry_config.sample.json")


def test_scene_manifest_schema():
    """world/scenes/scene-manifest.schema.json is a Phase W1 schema
    that had no sample/test until Phase W3 — extended, not duplicated
    (see world.frontend.scene.scene.Scene.to_manifest_dict, which
    keeps the dataclass and this schema from drifting apart)."""
    schema = _load(os.path.join(WORLD_ROOT, "scenes", "scene-manifest.schema.json"))
    sample = _load(os.path.join(WORLD_ROOT, "scenes", "scene-manifest.sample.json"))
    jsonschema.validate(instance=sample, schema=schema)


def test_minimap_schema():
    """world/minimap/minimap.schema.json — same situation as
    scene-manifest above: Phase W1 schema, no sample/test until now."""
    schema = _load(os.path.join(WORLD_ROOT, "minimap", "minimap.schema.json"))
    sample = _load(os.path.join(WORLD_ROOT, "minimap", "minimap.sample.json"))
    jsonschema.validate(instance=sample, schema=schema)


def test_scene_dataclass_matches_manifest_schema():
    """Scene.to_manifest_dict() output must itself validate against
    scene-manifest.schema.json — catches drift between the Python
    dataclass and the schema at the source, not just the sample."""
    schema = _load(os.path.join(WORLD_ROOT, "scenes", "scene-manifest.schema.json"))
    scene = Scene(scene_id="reception-scene-01", district_id="world-gateway", character_ids=["herald"])
    jsonschema.validate(instance=scene.to_manifest_dict(), schema=schema)
