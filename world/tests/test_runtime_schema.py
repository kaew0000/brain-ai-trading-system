"""Phase W4: the checked-in `world/data/runtime/*.json` placeholder
files must themselves validate against their schemas — not just
SnapshotBuilder's in-memory output (covered by
test_snapshot_builder.py). Catches drift if someone hand-edits a
runtime file without regenerating it via RuntimeManager."""

import json
import os

import jsonschema
import pytest

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.path.join(WORLD_ROOT, "data", "runtime")
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")

RUNTIME_FILE_TO_SCHEMA = {
    "world.json": "world.schema.json",
    "events.json": "events.schema.json",
    "missions.json": "missions.schema.json",
    "portfolio.json": "portfolio.schema.json",
    "telemetry.json": "telemetry.schema.json",
    "notifications.json": "notifications.schema.json",
    # Phase W12: workspace.json is UI layout state (world.workspace.
    # layout_manager), not a Phase W4 RuntimeManager snapshot — but it
    # lives in the same directory per this phase's own explicit
    # instruction, so it's covered by the same drift check.
    "workspace.json": "workspace.schema.json",
}


def _load(path):
    with open(path) as f:
        return json.load(f)


@pytest.mark.parametrize("runtime_file,schema_file", list(RUNTIME_FILE_TO_SCHEMA.items()))
def test_runtime_file_matches_schema(runtime_file, schema_file):
    data = _load(os.path.join(RUNTIME_DIR, runtime_file))
    schema = _load(os.path.join(SCHEMAS_DIR, schema_file))
    jsonschema.validate(instance=data, schema=schema)


def test_all_seven_runtime_files_present():
    assert set(os.listdir(RUNTIME_DIR)) == set(RUNTIME_FILE_TO_SCHEMA.keys())


def test_placeholder_world_state_is_honestly_idle():
    """No reader is wired to a real source yet - the checked-in
    world.json must say so truthfully, not fabricate 'active'."""
    data = _load(os.path.join(RUNTIME_DIR, "world.json"))
    assert data["engineStatus"] == "idle"
    assert data["activeDistricts"] == []
    assert data["activeAgents"] == []
