"""Phase W6: every real room is populated, and every populated room is real."""
import json
import os
import sys

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(WORLD_ROOT)
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from world.frontend.rooms.room_type import CirculationType  # noqa: E402

ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")
DISTRICT_DEFS_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _real_room_ids():
    dept_ids = {
        _load(os.path.join(DISTRICT_DEFS_DIR, f))["id"]
        for f in os.listdir(DISTRICT_DEFS_DIR) if f.endswith(".json")
    }
    return dept_ids | {c.value for c in CirculationType}


def test_every_real_room_has_a_room_assets_entry():
    room_assets = _load(os.path.join(ASSETS_DIR, "room_assets.json"))
    seen = {r["roomId"] for r in room_assets}
    assert seen == _real_room_ids()


def test_no_room_assets_entry_is_completely_empty():
    room_assets = _load(os.path.join(ASSETS_DIR, "room_assets.json"))
    for room in room_assets:
        total = len(room["furniturePlacements"]) + len(room["decorationPlacements"])
        assert total > 0, f"room {room['roomId']!r} has no furniture or decoration at all"


def test_room_placements_reference_real_furniture_and_decorations():
    room_assets = _load(os.path.join(ASSETS_DIR, "room_assets.json"))
    furniture_ids = {f["id"] for f in _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))}
    decoration_ids = {d["id"] for d in _load(os.path.join(ASSETS_DIR, "decoration_assets.json"))}
    for room in room_assets:
        for fp in room["furniturePlacements"]:
            assert fp["furnitureId"] in furniture_ids
        for dp in room["decorationPlacements"]:
            assert dp["decorationId"] in decoration_ids
