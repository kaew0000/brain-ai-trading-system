"""
Phase W6 validation: asset manifest, room population, character placement,
furniture/decoration catalogs, and dependency integrity.

Checks performed:
- every *.schema.json file added in Phase W6 is valid JSON
- asset_manifest.json has no duplicate ids
- every dependency referenced by a manifest entry exists in the manifest
  (no missing dependencies)
- every furniture_assets.json / decoration_assets.json entry's manifestId
  resolves to a real manifest entry
- every room in room_assets.json is a real department id (from
  world/districts/definitions/) or a real CirculationType id (from
  world/frontend/rooms/room_type.py) — no orphan rooms
- every real room (department + circulation type) has a room_assets.json
  entry — no missing rooms
- every furniture/decoration id referenced by a room placement exists in
  furniture_assets.json / decoration_assets.json respectively
- every character in character_assets.json / spatial_placement.json is a
  real character id (from world/characters/definitions/) — no orphan
  characters, and every real character has exactly one entry in each file
- no duplicate ids in any of the Phase W6 data files

This script never touches anything outside world/.
"""
import json
import os
import sys

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCHEMAS_DIR = os.path.join(WORLD_ROOT, "data", "schemas")
ASSETS_DIR = os.path.join(WORLD_ROOT, "data", "assets")
INTERACTIONS_DIR = os.path.join(WORLD_ROOT, "data", "interactions")
CHAR_DEFS_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")
DISTRICT_DEFS_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")
SPATIAL_PATH = os.path.join(WORLD_ROOT, "data", "characters", "spatial_placement.json")


def _load(path):
    with open(path) as f:
        return json.load(f)


def _known_department_ids():
    return sorted(
        _load(os.path.join(DISTRICT_DEFS_DIR, fname))["id"]
        for fname in os.listdir(DISTRICT_DEFS_DIR)
        if fname.endswith(".json")
    )


def _known_character_ids():
    return sorted(
        _load(os.path.join(CHAR_DEFS_DIR, fname))["id"]
        for fname in os.listdir(CHAR_DEFS_DIR)
        if fname.endswith(".json")
    )


def _circulation_ids():
    repo_root = os.path.dirname(WORLD_ROOT)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)
    from world.frontend.rooms.room_type import CirculationType
    return [c.value for c in CirculationType]


def validate_all():
    errors = []

    # 1. schema files parse
    for fname in sorted(os.listdir(SCHEMAS_DIR)):
        if fname.endswith(".schema.json"):
            try:
                _load(os.path.join(SCHEMAS_DIR, fname))
            except Exception as e:
                errors.append(f"Invalid JSON in schema {fname}: {e}")

    manifest = _load(os.path.join(ASSETS_DIR, "asset_manifest.json"))
    manifest_ids = [entry["id"] for entry in manifest]
    manifest_id_set = set(manifest_ids)

    if len(manifest_ids) != len(manifest_id_set):
        dupes = {i for i in manifest_ids if manifest_ids.count(i) > 1}
        errors.append(f"Duplicate ids in asset_manifest.json: {sorted(dupes)}")

    # 2. dependency integrity
    for entry in manifest:
        for dep in entry.get("dependencies", []):
            if dep not in manifest_id_set:
                errors.append(
                    f"asset_manifest entry {entry['id']!r} depends on missing id {dep!r}"
                )

    # 3. furniture / decoration catalogs resolve into the manifest
    furniture = _load(os.path.join(ASSETS_DIR, "furniture_assets.json"))
    decorations = _load(os.path.join(ASSETS_DIR, "decoration_assets.json"))

    furniture_ids = [f["id"] for f in furniture]
    if len(furniture_ids) != len(set(furniture_ids)):
        errors.append("Duplicate ids in furniture_assets.json")
    for f in furniture:
        if f["manifestId"] not in manifest_id_set:
            errors.append(f"furniture {f['id']!r} manifestId {f['manifestId']!r} not in manifest")

    decoration_ids = [d["id"] for d in decorations]
    if len(decoration_ids) != len(set(decoration_ids)):
        errors.append("Duplicate ids in decoration_assets.json")
    for d in decorations:
        if d["manifestId"] not in manifest_id_set:
            errors.append(f"decoration {d['id']!r} manifestId {d['manifestId']!r} not in manifest")

    furniture_id_set = {f["id"] for f in furniture}
    decoration_id_set = {d["id"] for d in decorations}

    # 4. room population — no orphan rooms, no missing rooms
    room_assets = _load(os.path.join(ASSETS_DIR, "room_assets.json"))
    real_room_ids = set(_known_department_ids()) | set(_circulation_ids())
    room_ids_seen = [r["roomId"] for r in room_assets]

    if len(room_ids_seen) != len(set(room_ids_seen)):
        errors.append("Duplicate roomId entries in room_assets.json")

    for room_id in room_ids_seen:
        if room_id not in real_room_ids:
            errors.append(f"room_assets.json references orphan room {room_id!r}")

    missing_rooms = real_room_ids - set(room_ids_seen)
    if missing_rooms:
        errors.append(f"room_assets.json is missing entries for rooms: {sorted(missing_rooms)}")

    for room in room_assets:
        for fp in room.get("furniturePlacements", []):
            if fp["furnitureId"] not in furniture_id_set:
                errors.append(
                    f"room {room['roomId']!r} references unknown furnitureId {fp['furnitureId']!r}"
                )
        for dp in room.get("decorationPlacements", []):
            if dp["decorationId"] not in decoration_id_set:
                errors.append(
                    f"room {room['roomId']!r} references unknown decorationId {dp['decorationId']!r}"
                )

    # 5. character coverage — no orphan characters, no missing characters
    character_assets = _load(os.path.join(ASSETS_DIR, "character_assets.json"))
    spatial = _load(SPATIAL_PATH)
    real_char_ids = set(_known_character_ids())

    ca_ids = [c["characterId"] for c in character_assets]
    sp_ids = [s["characterId"] for s in spatial]

    for label, ids in (("character_assets.json", ca_ids), ("spatial_placement.json", sp_ids)):
        if len(ids) != len(set(ids)):
            errors.append(f"Duplicate characterId entries in {label}")
        orphans = set(ids) - real_char_ids
        if orphans:
            errors.append(f"{label} references orphan character ids: {sorted(orphans)}")
        missing = real_char_ids - set(ids)
        if missing:
            errors.append(f"{label} is missing entries for characters: {sorted(missing)}")

    for c in character_assets:
        for anim, asset_id in c["spriteAssetIds"].items():
            if asset_id not in manifest_id_set:
                errors.append(
                    f"character {c['characterId']!r} {anim} sprite {asset_id!r} not in manifest"
                )

    # 6. interaction types referenced anywhere resolve to a known type
    interaction_types = _load(os.path.join(INTERACTIONS_DIR, "interaction_types.json"))
    interaction_ids = {t["id"] for t in interaction_types}
    if len(interaction_ids) != len(interaction_types):
        errors.append("Duplicate ids in interaction_types.json")

    for f in furniture:
        for i in f.get("defaultInteractions", []):
            if i not in interaction_ids:
                errors.append(f"furniture {f['id']!r} references unknown interaction {i!r}")
    for d in decorations:
        for i in d.get("defaultInteractions", []):
            if i not in interaction_ids:
                errors.append(f"decoration {d['id']!r} references unknown interaction {i!r}")
    for room in room_assets:
        for fp in room.get("furniturePlacements", []):
            for i in fp.get("interactions", []):
                if i not in interaction_ids:
                    errors.append(
                        f"room {room['roomId']!r} placement {fp['instanceId']!r} "
                        f"references unknown interaction {i!r}"
                    )

    # 7. asset packs reference only real manifest ids
    packs = _load(os.path.join(ASSETS_DIR, "asset_packs.json"))
    pack_ids = [p["id"] for p in packs]
    if len(pack_ids) != len(set(pack_ids)):
        errors.append("Duplicate ids in asset_packs.json")
    for p in packs:
        for asset_id in p["assetIds"]:
            if asset_id not in manifest_id_set:
                errors.append(f"asset pack {p['id']!r} references unknown asset {asset_id!r}")

    return errors


if __name__ == "__main__":
    errs = validate_all()
    if errs:
        print("VALIDATION FAILED:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    print("All Phase W6 asset/room/character data validated successfully.")
