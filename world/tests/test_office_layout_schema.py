"""Phase W2: schema validation for office layout, character placement, and
navigation graph data. Mirrors the existing test_schema_integrity.py pattern
but targets world/data/layout, world/data/characters, world/data/navigation
directly (these are canonical data, not *.sample.json files)."""
import json
import os

import jsonschema

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _schema(name):
    return _load(os.path.join(SCHEMAS_DIR, name))


def test_office_layout_matches_schema():
    schema = _schema("office_layout.schema.json")
    floors = _load(os.path.join(WORLD_ROOT, "data", "layout", "floors.json"))
    rooms = _load(os.path.join(WORLD_ROOT, "data", "layout", "rooms.json"))
    instance = {"floors": floors, "rooms": rooms}
    jsonschema.validate(instance=instance, schema=schema)


def test_office_characters_matches_schema():
    schema = _schema("office_characters.schema.json")
    placement = _load(os.path.join(WORLD_ROOT, "data", "characters", "placement.json"))
    jsonschema.validate(instance=placement, schema=schema)


def test_navigation_matches_schema():
    schema = _schema("navigation.schema.json")
    graph = _load(os.path.join(WORLD_ROOT, "data", "navigation", "graph.json"))
    jsonschema.validate(instance=graph, schema=schema)
