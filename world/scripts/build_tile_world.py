"""Build the Office World tile map from the CoolSchool tileset (V16 §94).

Everything that describes the world - grid, room layout, sprite crops, furniture footprints, seats,
floor colours - lives in ``world/data/assets/tile_world.json``; nothing is hard-coded here. Character
-> room placement comes from ``world/data/characters/placement.json`` and room names from
``world/data/layout/rooms.json`` (the same canon the rest of World reads), so a seat can never drift
from the backend's idea of where a character works.

Writes (deterministic, so the committed files can be diffed against a rebuild):

* ``dashboard_src/public/assets/world/tile/atlas.png`` + ``atlas.json`` - Phaser "hash" atlas
* ``dashboard_src/public/assets/world/tile/office.map.json`` - floor layer, collision rows, props, rooms, seats

The build refuses (ValueError) a layout where a seat, meeting spot or the spawn cannot be reached
on foot from every room door, where a character has no seat, or where furniture leaves its room.

Usage: ``python -m world.scripts.build_tile_world [--preview out.png]``
"""
from __future__ import annotations

import argparse
import json
import os
from collections import deque
from typing import Any

from PIL import Image

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(WORLD_ROOT)
SPEC_PATH = os.path.join(WORLD_ROOT, "data", "assets", "tile_world.json")
SOURCE_DIR = os.path.join(WORLD_ROOT, "data", "assets", "source")
PLACEMENT_PATH = os.path.join(WORLD_ROOT, "data", "characters", "placement.json")
ROOMS_PATH = os.path.join(WORLD_ROOT, "data", "layout", "rooms.json")
OUT_DIR = os.path.join(REPO_ROOT, "dashboard_src", "public", "assets", "world", "tile")
ATLAS_WIDTH = 1024
ATLAS_PAD = 2

Tile = tuple[int, int]


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ── art ──────────────────────────────────────────────────────────────────────

def _crop(sheet: Image.Image, rect: list[int], trim: bool) -> Image.Image:
    x, y, w, h = rect
    img = sheet.crop((x, y, x + w, y + h))
    if not trim:
        return img
    box = img.getchannel("A").getbbox()
    if box is None:
        raise ValueError(f"crop {rect} is fully transparent")
    return img.crop(box)


def _shift_hue(img: Image.Image, degrees: int, saturation: float = 1.0) -> Image.Image:
    """Hue-rotate the opaque pixels of ``img`` by ``degrees`` (0..255 PIL hue units) and scale saturation."""
    alpha = img.getchannel("A")
    h, s, v = img.convert("RGB").convert("HSV").split()
    h = h.point(lambda value: (value + degrees) % 256)
    s = s.point(lambda value: min(255, round(value * saturation)))
    out = Image.merge("HSV", (h, s, v)).convert("RGB").convert("RGBA")
    out.putalpha(alpha)
    return out


def build_art(spec: dict[str, Any], source_png: str) -> dict[str, Image.Image]:
    sheet = Image.open(source_png).convert("RGBA")
    art: dict[str, Image.Image] = {}
    for name, rect in spec["tiles"].items():
        art[name] = _crop(sheet, rect, trim=False)
    for name, degrees in spec["floorVariants"].items():
        art[name] = _shift_hue(art["floor_yellow"], degrees, spec.get("floorSaturation", 1.0))
    for name, rect in spec["sprites"].items():
        art[name] = _crop(sheet, rect, trim=True)
    return art


def pack_atlas(art: dict[str, Image.Image]) -> tuple[Image.Image, dict[str, Any]]:
    """Shelf-pack ``art`` (tallest first, name as tiebreak) into one sheet; returns (image, Phaser hash atlas)."""
    order = sorted(art, key=lambda n: (-art[n].height, n))
    placed: dict[str, tuple[int, int]] = {}
    x = y = row_h = 0
    for name in order:
        w, h = art[name].size
        if x + w + ATLAS_PAD > ATLAS_WIDTH:
            x, y, row_h = 0, y + row_h + ATLAS_PAD, 0
        placed[name] = (x, y)
        x += w + ATLAS_PAD
        row_h = max(row_h, h)
    height = 1
    while height < y + row_h + ATLAS_PAD:
        height *= 2
    atlas = Image.new("RGBA", (ATLAS_WIDTH, height), (0, 0, 0, 0))
    frames: dict[str, Any] = {}
    for name in sorted(placed):
        px, py = placed[name]
        w, h = art[name].size
        atlas.paste(art[name], (px, py))
        frames[name] = {
            "frame": {"x": px, "y": py, "w": w, "h": h},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h},
            "sourceSize": {"w": w, "h": h},
        }
    meta = {"image": "atlas.png", "format": "RGBA8888", "size": {"w": ATLAS_WIDTH, "h": height}, "scale": "1"}
    return atlas, {"frames": frames, "meta": meta}


# ── map ──────────────────────────────────────────────────────────────────────

def _band_geometry(spec: dict[str, Any], band: str) -> tuple[int, int]:
    """(first wall row, first interior row) of a room band."""
    g = spec["grid"][band]
    return g["top"], g["top"] + g["wallRows"]


def _walkable_neighbours(blocked: set[Tile], tile: Tile, cols: int, rows: int) -> list[Tile]:
    x, y = tile
    out = []
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < cols and 0 <= ny < rows and (nx, ny) not in blocked:
            out.append((nx, ny))
    return out


def _distances(blocked: set[Tile], start: Tile, cols: int, rows: int) -> dict[Tile, int]:
    dist = {start: 0}
    queue = deque([start])
    while queue:
        cur = queue.popleft()
        for nxt in _walkable_neighbours(blocked, cur, cols, rows):
            if nxt not in dist:
                dist[nxt] = dist[cur] + 1
                queue.append(nxt)
    return dist


def build_map(spec: dict[str, Any], placement: list[dict[str, Any]], room_names: dict[str, str]) -> dict[str, Any]:
    ts = spec["tileSize"]
    cols, rows = spec["grid"]["cols"], spec["grid"]["rows"]
    rw, iw, ih = spec["grid"]["roomWidth"], spec["grid"]["interiorWidth"], spec["grid"]["interiorHeight"]
    door_cols = spec["grid"]["doorTiles"]
    furniture = spec["furniture"]
    lift_top = spec["onTopLiftPx"]
    wall_lift = spec.get("wallItemLiftPx", 0)

    tile_names = ["wall_a", "wall_b", "floor_yellow", *sorted(spec["floorVariants"])]
    tile_index = {n: i for i, n in enumerate(tile_names)}
    floor = [[tile_index["floor_yellow"]] * cols for _ in range(rows)]
    blocked: set[Tile] = set()

    def wall(x: int, y: int, name: str = "wall_b") -> None:
        floor[y][x] = tile_index[name]
        blocked.add((x, y))

    rooms_out: list[dict[str, Any]] = []
    props: list[dict[str, Any]] = []
    door_tiles: dict[str, list[Tile]] = {}  # room id -> the wall cells that are door gaps (walkable)
    inside_door: dict[str, Tile] = {}
    pending_items: list[tuple[str, dict[str, Any], int, int, int, int]] = []  # room, item, ox, oy, ixmax, iymax

    def add_item(room_id: str, item: dict[str, Any], ox: int, oy: int, interior: tuple[int, int] | None) -> None:
        name = item["item"]
        if name not in furniture:
            raise ValueError(f"{room_id}: unknown furniture {name!r}")
        fw, fh = furniture[name]["footprint"]
        is_wall = bool(furniture[name].get("wall"))
        on_top = bool(furniture[name].get("onTop"))
        x, y = item["x"], item["y"]
        if interior is not None:
            if not is_wall and not (0 <= x and x + fw <= interior[0] and 0 <= y and y + fh <= interior[1]):
                raise ValueError(f"{room_id}: {name} at ({x},{y}) leaves the room")
            if is_wall and not (0 <= x and x + fw <= interior[0] and y == -1):
                raise ValueError(f"{room_id}: wall item {name} must sit on interior row -1 inside the room")
        tx, ty = ox + x, oy + y
        anchor_x = (tx + fw / 2) * ts + item.get("dx", 0)
        anchor_y = (ty + fh) * ts + item.get("dy", 0)
        if on_top:
            anchor_y -= lift_top
        if is_wall:
            anchor_y -= wall_lift
        depth = anchor_y + (0.5 if on_top else 0)
        props.append({"frame": name, "x": round(anchor_x, 1), "y": round(anchor_y, 1), "depth": round(depth, 1), "room": room_id})
        if not is_wall and not on_top and item.get("block", True):
            for ix in range(fw):
                for iy in range(fh):
                    blocked.add((tx + ix, ty + iy))

    # outer shell of both room bands: vertical walls first so the horizontal rows (wall_a on the
    # top row) win at the corners, then each room
    for band in ("north", "south"):
        wall_top, interior_top = _band_geometry(spec, band)
        bottom = interior_top + ih  # one wall row below the interior
        for r in range(wall_top, bottom + 1):
            for slot in range(cols // rw + 1):
                wall(min(slot * rw, cols - 1), r)
        for x in range(cols):
            for r in range(wall_top, interior_top):
                wall(x, r, "wall_a" if r == wall_top else "wall_b")
            wall(x, bottom)
    for r in range(spec["grid"]["hall"]["top"], spec["grid"]["hall"]["top"] + spec["grid"]["hall"]["rows"]):
        wall(0, r)
        wall(cols - 1, r)

    for room_id, room in spec["rooms"].items():
        band, slot = room["band"], room["slot"]
        wall_top, interior_top = _band_geometry(spec, band)
        ox, oy = slot * rw + 1, interior_top
        for ix in range(iw):
            for iy in range(ih):
                floor[oy + iy][ox + ix] = tile_index[room["floor"]]
                blocked.discard((ox + ix, oy + iy))
        # door gap: bottom wall row of a north room, both top wall rows of a south room
        gap_rows = [oy + ih] if band == "north" else list(range(wall_top, interior_top))
        gaps = [(ox + c, r) for c in door_cols for r in gap_rows]
        for gx, gy in gaps:
            floor[gy][gx] = tile_index["floor_yellow"]
            blocked.discard((gx, gy))
        door_tiles[room_id] = gaps
        inside_door[room_id] = (ox + door_cols[0], oy + ih - 1) if band == "north" else (ox + door_cols[0], oy)
        pending_items.append((room_id, room, ox, oy, iw, ih))

    for area_id, area in spec["special"].items():
        x0, y0, w, h = area["rect"]
        for ax in range(x0, x0 + w):
            for ay in range(y0, y0 + h):
                floor[ay][ax] = tile_index[area["floor"]]

    # furniture (after every floor/wall write so footprints always win)
    seat_chair = spec["seatChair"]
    for room_id, room, ox, oy, iwid, ihei in pending_items:
        for item in room["items"]:
            add_item(room_id, item, ox, oy, (iwid, ihei))
    for area_id, area in spec["special"].items():
        for item in area["items"]:
            add_item(area_id, item, 0, 0, None)

    # seats + character assignment
    by_room: dict[str, list[str]] = {}
    for entry in placement:
        by_room.setdefault(entry["roomId"], []).append(entry["characterId"])
    for room_id, chars in by_room.items():
        if room_id not in spec["rooms"]:
            raise ValueError(f"placement.json puts characters in {room_id!r} but the layout has no such room")
        if len(chars) > len(spec["rooms"][room_id]["seats"]):
            raise ValueError(f"{room_id}: {len(chars)} characters but only {len(spec['rooms'][room_id]['seats'])} seats")

    for room_id, room, ox, oy, iwid, ihei in pending_items:
        chars = by_room.get(room_id, [])
        chair = room.get("seatChair", seat_chair)
        seats = []
        for i, seat in enumerate(room["seats"]):
            tile = (ox + seat["x"], oy + seat["y"])
            if tile in blocked:
                raise ValueError(f"{room_id}: seat {tile} is inside furniture or a wall")
            seats.append({"tile": list(tile), "facing": seat["facing"], "character": chars[i] if i < len(chars) else None})
            cx = (tile[0] + 0.5) * ts
            by = (tile[1] + 1) * ts - 4
            props.append({"frame": chair, "x": round(cx, 1), "y": round(by, 1), "depth": round(tile[1] * ts + 40 - 1, 1), "room": room_id})
        room["_seats"] = seats

    # reachability from every door
    reach_from: dict[str, dict[Tile, int]] = {}
    for room_id, room, ox, oy, iwid, ihei in pending_items:
        reach_from[room_id] = _distances(blocked, inside_door[room_id], cols, rows)

    spawn = tuple(spec["spawn"]["tile"])
    if spawn in blocked:
        raise ValueError(f"spawn {spawn} is blocked")
    spawn_dist = _distances(blocked, spawn, cols, rows)

    for room_id, room, ox, oy, iwid, ihei in pending_items:
        dist = reach_from[room_id]
        interior = [(ox + ix, oy + iy) for ix in range(iw) for iy in range(ih) if (ox + ix, oy + iy) not in blocked]
        for seat in room["_seats"]:
            if tuple(seat["tile"]) not in dist:
                raise ValueError(f"{room_id}: seat {seat['tile']} cannot be reached from the door")
        for gx, gy in door_tiles[room_id]:
            if (gx, gy) not in spawn_dist:
                raise ValueError(f"{room_id}: door {(gx, gy)} cannot be reached from the spawn")
        reachable = [t for t in interior if t in dist]
        seat_tiles = {tuple(s["tile"]) for s in room["_seats"]}
        free = [t for t in reachable if t not in seat_tiles]
        if len(free) < 2:
            raise ValueError(f"{room_id}: fewer than two free reachable tiles")
        centre = (ox + iw // 2, oy + ih // 2)
        meet = min(free, key=lambda t: (abs(t[0] - centre[0]) + abs(t[1] - centre[1]), t[1], t[0]))
        step = max(1, len(free) // spec.get("wanderPoints", 12))
        wander = sorted(free, key=lambda t: (t[1], t[0]))[::step]
        rooms_out.append({
            "id": room_id,
            "name": room_names.get(room_id, room_id),
            "rect": [ox, oy, iw, ih],
            "door": list(inside_door[room_id]),
            "meet": list(meet),
            "seats": room["_seats"],
            "wander": [list(t) for t in wander],
        })

    for area_id, area in spec["special"].items():
        x0, y0, w, h = area["rect"]
        meet = tuple(area["meet"])
        if meet in blocked or meet not in spawn_dist:
            raise ValueError(f"{area_id}: meeting tile {meet} is blocked or unreachable")
        free = sorted((x, y) for x in range(x0, x0 + w) for y in range(y0, y0 + h) if (x, y) not in blocked and (x, y) in spawn_dist)
        step = max(1, len(free) // spec.get("wanderPoints", 12))
        rooms_out.append({
            "id": area_id,
            "name": room_names.get(area_id, area_id.capitalize()),
            "rect": [x0, y0, w, h],
            "door": list(meet),
            "meet": list(meet),
            "seats": [],
            "wander": [list(t) for t in sorted(free, key=lambda t: (t[1], t[0]))[::step]],
        })

    props.sort(key=lambda p: (p["depth"], p["x"], p["frame"]))
    collision = ["".join("#" if (x, y) in blocked else "." for x in range(cols)) for y in range(rows)]
    return {
        "version": spec["version"],
        "tileSize": ts,
        "cols": cols,
        "rows": rows,
        "width": cols * ts,
        "height": rows * ts,
        "tiles": tile_names,
        "floor": floor,
        "collision": collision,
        "props": props,
        "rooms": sorted(rooms_out, key=lambda r: r["id"]),
        "spawn": {"tile": list(spawn), "facing": spec["spawn"]["facing"]},
    }


# ── preview + CLI ────────────────────────────────────────────────────────────

def render_preview(world: dict[str, Any], art: dict[str, Image.Image]) -> Image.Image:
    ts = world["tileSize"]
    img = Image.new("RGBA", (world["width"], world["height"]), (15, 23, 42, 255))
    for y, row in enumerate(world["floor"]):
        for x, idx in enumerate(row):
            img.alpha_composite(art[world["tiles"][idx]], (x * ts, y * ts))
    for p in sorted(world["props"], key=lambda q: q["depth"]):
        sprite = art[p["frame"]]
        img.alpha_composite(sprite, (round(p["x"] - sprite.width / 2), round(p["y"] - sprite.height)))
    return img


def _dump(path: str, data: Any) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, sort_keys=True, separators=(",", ":"))
        f.write("\n")


def build(out_dir: str = OUT_DIR, spec_path: str = SPEC_PATH) -> dict[str, Any]:
    spec = _load(spec_path)
    art = build_art(spec, os.path.join(SOURCE_DIR, spec["source"]["file"]))
    atlas_img, atlas_data = pack_atlas(art)
    placement = _load(PLACEMENT_PATH)
    room_names = {r["id"]: r["name"] for r in _load(ROOMS_PATH)}
    world = build_map(spec, placement, room_names)
    os.makedirs(out_dir, exist_ok=True)
    atlas_img.save(os.path.join(out_dir, "atlas.png"), optimize=True)
    _dump(os.path.join(out_dir, "atlas.json"), atlas_data)
    _dump(os.path.join(out_dir, "office.map.json"), world)
    world["_art"] = art  # for the preview only; never written
    return world


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--preview", help="also write a full-map PNG preview here")
    parser.add_argument("--out", default=OUT_DIR, help="output directory (default: the dashboard's public assets)")
    args = parser.parse_args(argv)
    world = build(args.out)
    art = world.pop("_art")
    if args.preview:
        render_preview(world, art).save(args.preview)
    print(f"tile world: {world['cols']}x{world['rows']} tiles, {len(world['props'])} props, {len(world['rooms'])} rooms -> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
