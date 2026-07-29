"""Phase W2: every office layout/placement reference must point at a real,
already-existing district or character — this phase adds a spatial layer on
top of Phase W1 data, it never invents new departments or agents."""
import json
import os

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")
CHAR_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")


def _known_district_ids():
    ids = set()
    for fname in os.listdir(DIST_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(DIST_DIR, fname)) as f:
                ids.add(json.load(f)["id"])
    return ids


def _known_characters():
    chars = {}
    for fname in os.listdir(CHAR_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(CHAR_DIR, fname)) as f:
                c = json.load(f)
                chars[c["id"]] = c
    return chars


def _rooms():
    with open(os.path.join(WORLD_ROOT, "data", "layout", "rooms.json")) as f:
        return json.load(f)


def _placement():
    with open(os.path.join(WORLD_ROOT, "data", "characters", "placement.json")) as f:
        return json.load(f)


def test_every_room_id_is_a_known_district():
    ids = _known_district_ids()
    for r in _rooms():
        assert r["id"] in ids, f"room {r['id']} is not a known district — W2 must not invent new departments"


def test_room_count_matches_district_count():
    assert len(_rooms()) == len(_known_district_ids())


def test_floor_plan_covers_every_room_exactly_once():
    with open(os.path.join(WORLD_ROOT, "data", "layout", "floors.json")) as f:
        floors = json.load(f)
    all_floor_rooms = [rid for f in floors for rid in f["rooms"]]
    room_ids = {r["id"] for r in _rooms()}
    assert set(all_floor_rooms) == room_ids
    assert len(all_floor_rooms) == len(set(all_floor_rooms)), "a room appears on more than one floor"


def test_room_connections_reference_known_rooms():
    ids = {r["id"] for r in _rooms()}
    for r in _rooms():
        for conn in r["connections"]:
            assert conn in ids, f"{r['id']} connects to unknown room {conn}"


def test_placement_references_known_characters_and_rooms():
    chars = _known_characters()
    room_ids = {r["id"] for r in _rooms()}
    seen_characters = set()
    for p in _placement():
        assert p["characterId"] in chars, f"unknown characterId {p['characterId']}"
        assert chars[p["characterId"]]["agentRef"] == p["agentRef"], (
            f"agentRef mismatch for {p['characterId']}"
        )
        assert p["roomId"] in room_ids, f"unknown roomId {p['roomId']}"
        seen_characters.add(p["characterId"])

    assert seen_characters == set(chars.keys()), "every existing character must have a placement entry"


def test_placement_room_matches_character_home_district():
    chars = _known_characters()
    for p in _placement():
        home_district = chars[p["characterId"]]["district"]
        assert p["roomId"] == home_district, (
            f"{p['characterId']} placed in {p['roomId']} but its home district is {home_district}"
        )
