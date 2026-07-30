"""Phase W6: no duplicate ids anywhere in the new asset/room/character data."""
import json
import os

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")
INTERACTIONS_DIR = os.path.join(WORLD_ROOT, "data", "interactions")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _assert_unique(ids, label):
    assert len(ids) == len(set(ids)), f"Duplicate ids found in {label}: {ids}"


def test_asset_manifest_ids_unique():
    manifest = _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))
    _assert_unique([e["id"] for e in manifest], "asset_manifest.json")


def test_furniture_ids_unique():
    furniture = _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))
    _assert_unique([f["id"] for f in furniture], "furniture_assets.json")


def test_decoration_ids_unique():
    decorations = _load(os.path.join(ASSETS_DIR, "decoration_assets.json"))
    _assert_unique([d["id"] for d in decorations], "decoration_assets.json")


def test_asset_pack_ids_unique():
    packs = _load(os.path.join(ASSETS_DIR, "asset_packs.json"))
    _assert_unique([p["id"] for p in packs], "asset_packs.json")


def test_interaction_type_ids_unique():
    interactions = _load(os.path.join(INTERACTIONS_DIR, "interaction_types.json"))
    _assert_unique([i["id"] for i in interactions], "interaction_types.json")


def test_room_instance_ids_unique_within_each_room():
    room_assets = _load(os.path.join(ASSETS_DIR, "room_assets.json"))
    for room in room_assets:
        furn_instance_ids = [fp["instanceId"] for fp in room["furniturePlacements"]]
        deco_instance_ids = [dp["instanceId"] for dp in room["decorationPlacements"]]
        _assert_unique(furn_instance_ids, f"{room['roomId']} furniturePlacements")
        _assert_unique(deco_instance_ids, f"{room['roomId']} decorationPlacements")
