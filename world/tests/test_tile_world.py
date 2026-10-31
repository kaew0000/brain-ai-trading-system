"""V16 §94: tile world build - committed assets match a rebuild, layout invariants, and the builder's refusals."""
from __future__ import annotations

import copy
import json
import os

import pytest
from PIL import Image, ImageChops

from world.scripts import build_tile_world as btw


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@pytest.fixture(scope="module")
def spec():
    return _load(btw.SPEC_PATH)


@pytest.fixture(scope="module")
def placement():
    return _load(btw.PLACEMENT_PATH)


@pytest.fixture(scope="module")
def names():
    return {r["id"]: r["name"] for r in _load(btw.ROOMS_PATH)}


@pytest.fixture(scope="module")
def rebuilt(tmp_path_factory):
    out = tmp_path_factory.mktemp("tile_world")
    btw.build(str(out))
    return str(out)


def test_committed_assets_match_a_fresh_build(rebuilt):
    """Fails when someone edits tile_world.json / the script without re-running the build (or hand-edits the output)."""
    for name in ("office.map.json", "atlas.json"):
        with open(os.path.join(rebuilt, name), "rb") as a, open(os.path.join(btw.OUT_DIR, name), "rb") as b:
            assert a.read() == b.read(), f"{name} is stale: run python -m world.scripts.build_tile_world"
    fresh = Image.open(os.path.join(rebuilt, "atlas.png")).convert("RGBA")
    committed = Image.open(os.path.join(btw.OUT_DIR, "atlas.png")).convert("RGBA")
    assert fresh.size == committed.size
    assert ImageChops.difference(fresh, committed).getbbox() is None, "atlas.png is stale"


def test_build_is_deterministic(rebuilt, tmp_path):
    btw.build(str(tmp_path))
    for name in ("office.map.json", "atlas.json"):
        with open(os.path.join(rebuilt, name), "rb") as a, open(tmp_path / name, "rb") as b:
            assert a.read() == b.read()


def test_every_backend_room_and_character_is_in_the_map(spec, placement, names):
    world = btw.build_map(copy.deepcopy(spec), placement, names)
    ids = {r["id"] for r in world["rooms"]}
    assert set(names) <= ids                      # the 14 districts
    assert {"lobby", "hallway", "elevator"} <= ids  # the 3 non-district rooms the simulation also has
    assert len(ids) == 17
    seated = {s["character"] for r in world["rooms"] for s in r["seats"] if s["character"]}
    assert seated == {p["characterId"] for p in placement}


def test_atlas_covers_every_drawn_frame(rebuilt):
    world = _load(os.path.join(rebuilt, "office.map.json"))
    frames = set(_load(os.path.join(rebuilt, "atlas.json"))["frames"])
    assert {p["frame"] for p in world["props"]} <= frames
    assert set(world["tiles"]) <= frames


def test_atlas_frames_stay_inside_the_sheet_and_do_not_overlap(rebuilt):
    atlas = _load(os.path.join(rebuilt, "atlas.json"))
    w, h = atlas["meta"]["size"]["w"], atlas["meta"]["size"]["h"]
    boxes = [(f["frame"]["x"], f["frame"]["y"], f["frame"]["x"] + f["frame"]["w"], f["frame"]["y"] + f["frame"]["h"]) for f in atlas["frames"].values()]
    for x0, y0, x1, y1 in boxes:
        assert 0 <= x0 < x1 <= w and 0 <= y0 < y1 <= h
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1], "overlapping atlas frames"


def test_map_shape(rebuilt):
    world = _load(os.path.join(rebuilt, "office.map.json"))
    assert len(world["collision"]) == world["rows"] and all(len(r) == world["cols"] for r in world["collision"])
    assert len(world["floor"]) == world["rows"] and all(len(r) == world["cols"] for r in world["floor"])
    assert all(0 <= i < len(world["tiles"]) for row in world["floor"] for i in row)
    assert world["width"] == world["cols"] * world["tileSize"]


# ── the builder refuses broken layouts ───────────────────────────────────────

def test_rejects_a_seat_inside_furniture(spec, placement, names):
    bad = copy.deepcopy(spec)
    room = bad["rooms"]["ceo-tower"]
    sx, sy = room["seats"][0]["x"], room["seats"][0]["y"]
    room["items"].append({"item": "cab_a", "x": sx, "y": sy})
    with pytest.raises(ValueError, match="seat"):
        btw.build_map(bad, placement, names)


def test_rejects_a_walled_in_seat(spec, placement, names):
    bad = copy.deepcopy(spec)
    room = bad["rooms"]["ceo-tower"]
    sx, sy = room["seats"][0]["x"], room["seats"][0]["y"]
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        x, y = sx + dx, sy + dy
        if 0 <= x < 5 and 0 <= y < 7 and not any(i["x"] == x and i["y"] == y for i in room["items"]):
            room["items"].append({"item": "cab_a", "x": x, "y": y})
    with pytest.raises(ValueError, match="cannot be reached"):
        btw.build_map(bad, placement, names)


def test_rejects_furniture_leaving_its_room(spec, placement, names):
    bad = copy.deepcopy(spec)
    bad["rooms"]["ceo-tower"]["items"].append({"item": "desk_l", "x": 4, "y": 3})
    with pytest.raises(ValueError, match="leaves the room"):
        btw.build_map(bad, placement, names)


def test_rejects_unknown_furniture(spec, placement, names):
    bad = copy.deepcopy(spec)
    bad["rooms"]["ceo-tower"]["items"].append({"item": "no_such_thing", "x": 0, "y": 0})
    with pytest.raises(ValueError, match="unknown furniture"):
        btw.build_map(bad, placement, names)


def test_rejects_more_characters_than_seats(spec, placement, names):
    extra = placement + [{"characterId": "extra", "roomId": "ceo-tower"}]
    with pytest.raises(ValueError, match="only 1 seats"):
        btw.build_map(copy.deepcopy(spec), extra, names)


def test_rejects_a_character_in_an_unknown_room(spec, placement, names):
    extra = placement + [{"characterId": "ghost", "roomId": "nowhere"}]
    with pytest.raises(ValueError, match="no such room"):
        btw.build_map(copy.deepcopy(spec), extra, names)


def test_rejects_a_blocked_spawn(spec, placement, names):
    bad = copy.deepcopy(spec)
    bad["spawn"]["tile"] = [0, 0]
    with pytest.raises(ValueError, match="spawn"):
        btw.build_map(bad, placement, names)
