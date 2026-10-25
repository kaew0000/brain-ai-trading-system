"""Deterministic generator for the Office World isometric art (W-ISO-2).

Single source of truth: ``world/data/assets/iso_assets.json`` (tile size,
prop footprints/heights, per-character look, pose list). This script turns
that spec into:

* ``dashboard_src/public/assets/world/iso/props/<key>.png``
* ``dashboard_src/public/assets/world/iso/npc/<character>.png`` (one row of
  pose frames; frame order == ``character.poses`` in the spec)
* the ``iso`` block of ``dashboard_src/public/assets/world/manifest.json``
  (size / anchor / footprint / height per asset, so depth sorting and
  occlusion are data-driven)
* additive backend catalog entries (``asset_manifest.json``,
  ``character_assets.json``, ``furniture_assets.json``)

Everything is pure drawing code - no randomness, no network, no third-party
art - so re-running it is a no-op on a clean checkout (asserted by
``world/tests/test_iso_assets.py``).

Usage: ``python -m world.scripts.generate_iso_assets [--check]``
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from PIL import Image, ImageDraw

_HERE = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_HERE)
REPO_ROOT = os.path.dirname(WORLD_ROOT)
DATA_DIR = os.path.join(WORLD_ROOT, "data", "assets")
SPEC_PATH = os.path.join(DATA_DIR, "iso_assets.json")
FRONTEND_ASSETS = os.path.join(REPO_ROOT, "dashboard_src", "public", "assets", "world")
FRONTEND_MANIFEST = os.path.join(FRONTEND_ASSETS, "manifest.json")
ISO_DIR = os.path.join(FRONTEND_ASSETS, "iso")

#: Backend catalog states added by this phase (``working-seated`` is iso-only).
NEW_CHARACTER_STATES = ("meeting", "resting", "working-seated")


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _dump(path: str, data: Any, indent: int = 2) -> bytes:
    return (json.dumps(data, indent=indent, ensure_ascii=False) + "\n").encode("utf-8")


def _rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _shade(rgb: tuple[int, int, int], factor: float) -> tuple[int, int, int]:
    return tuple(max(0, min(255, int(c * factor))) for c in rgb)  # type: ignore[return-value]


# --------------------------------------------------------------------------
# Props
# --------------------------------------------------------------------------


class _IsoCanvas:
    """Draws axis-aligned boxes in a footprint-local grid (units = tiles)."""

    def __init__(self, spec: dict[str, Any], footprint: tuple[int, int], height: int) -> None:
        self.ss = int(spec["supersample"])
        self.tw = spec["tile"]["width"]
        self.th = spec["tile"]["height"]
        margin = int(spec["propMargin"])
        self.a, self.b = footprint
        self.w = int((self.a + self.b) * self.tw / 2) + 2 * margin
        self.h = int((self.a + self.b) * self.th / 2) + height + 2 * margin
        self.ox = self.b * self.tw / 2 + margin
        self.oy = height + margin
        self.img = Image.new("RGBA", (self.w * self.ss, self.h * self.ss), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.img)

    def pt(self, gx: float, gy: float, z: float = 0.0) -> tuple[float, float]:
        sx = (gx - gy) * self.tw / 2 + self.ox
        sy = (gx + gy) * self.th / 2 + self.oy - z
        return sx * self.ss, sy * self.ss

    def box(self, x0: float, y0: float, x1: float, y1: float, z0: float, z1: float,
            color: tuple[int, int, int], front: tuple[int, int, int] | None = None) -> None:
        left = [self.pt(x0, y1, z0), self.pt(x1, y1, z0), self.pt(x1, y1, z1), self.pt(x0, y1, z1)]
        right = [self.pt(x1, y1, z0), self.pt(x1, y0, z0), self.pt(x1, y0, z1), self.pt(x1, y1, z1)]
        top = [self.pt(x0, y0, z1), self.pt(x1, y0, z1), self.pt(x1, y1, z1), self.pt(x0, y1, z1)]
        self.d.polygon(left, fill=front or _shade(color, 0.8))
        self.d.polygon(right, fill=_shade(color, 0.62))
        self.d.polygon(top, fill=color)

    def ellipse(self, gx: float, gy: float, z: float, rx: float, ry: float,
                color: tuple[int, int, int]) -> None:
        cx, cy = self.pt(gx, gy, z)
        self.d.ellipse([cx - rx * self.ss, cy - ry * self.ss, cx + rx * self.ss, cy + ry * self.ss], fill=color)

    def finish(self) -> Image.Image:
        return self.img.resize((self.w, self.h), Image.LANCZOS)

    def anchor(self) -> list[float]:
        ax, ay = self.pt(self.a / 2, self.b / 2, 0.0)
        return [round(ax / self.ss / self.w, 4), round(ay / self.ss / self.h, 4)]


def _draw_prop(spec: dict[str, Any], prop: dict[str, Any]) -> tuple[Image.Image, list[float]]:
    a, b = prop["footprint"]
    height = int(prop["height"])
    c = _IsoCanvas(spec, (a, b), height)
    col, acc = _rgb(prop["color"]), _rgb(prop["accent"])
    shape = prop["shape"]
    if shape == "desk":
        c.box(0.05, 0.1, 0.2, b - 0.1, 0, height - 4, _shade(col, 0.85))
        c.box(a - 0.2, 0.1, a - 0.05, b - 0.1, 0, height - 4, _shade(col, 0.85))
        c.box(0, 0, a, b, height - 4, height, col)
    elif shape == "chair":
        c.box(0.4, 0.4, 0.6, 0.6, 0, 12, acc)
        c.box(0.2, 0.2, 0.8, 0.8, 12, 16, col)
        c.box(0.2, 0.1, 0.8, 0.25, 16, height, col)
    elif shape == "monitor":
        c.box(0.3, 0.3, 0.7, 0.7, 0, 2, acc)
        c.box(0.45, 0.45, 0.55, 0.55, 2, 10, col)
        c.box(0.08, 0.42, 0.92, 0.54, 10, height, col, front=acc)
    elif shape == "table":
        c.box(a / 2 - 0.3, b / 2 - 0.3, a / 2 + 0.3, b / 2 + 0.3, 0, height - 3, acc)
        c.box(0.1, 0.1, a - 0.1, b - 0.1, height - 3, height, col)
    elif shape == "rack":
        c.box(0.1, 0.1, 0.9, 0.9, 0, height, col)
        for i in range(6):  # status LEDs on the front-left face
            z = 8 + i * 9
            lx, ly = c.pt(0.18 + (i % 2) * 0.3, 0.9, z)
            c.d.rectangle([lx, ly - 2 * c.ss, lx + 6 * c.ss, ly], fill=acc if i % 3 else _shade(acc, 0.5))
    elif shape == "plant":
        c.box(0.3, 0.3, 0.7, 0.7, 0, 12, col)
        for dx, dy, z, r in ((0.5, 0.5, 22, 11), (0.4, 0.55, 28, 8), (0.62, 0.45, 30, 8), (0.5, 0.5, 38, 6)):
            c.ellipse(dx, dy, z, r, r * 0.9, _shade(acc, 0.8 + 0.1 * (z % 3)))
    elif shape == "partition":
        c.box(0, b / 2 - 0.08, a, b / 2 + 0.08, 0, height, col)
        c.box(0, b / 2 - 0.1, a, b / 2 + 0.1, height - 3, height, acc)
    elif shape == "sofa":
        c.box(0, 0.2, a, 1.0, 0, 12, col)
        c.box(0, 0.2, a, 0.45, 12, height, col)
        c.box(0, 0.45, 0.22, 1.0, 12, 20, _shade(col, 0.9))
        c.box(a - 0.22, 0.45, a, 1.0, 12, 20, _shade(col, 0.9))
    else:
        raise ValueError(f"unknown prop shape {shape!r} for {prop['key']!r}")
    return c.finish(), c.anchor()


# --------------------------------------------------------------------------
# Characters
# --------------------------------------------------------------------------


def _draw_character(spec: dict[str, Any], look: dict[str, str], pose: str) -> Image.Image:
    cfg = spec["character"]
    ss = int(spec["supersample"])
    fw, fh = cfg["frameWidth"], cfg["frameHeight"]
    img = Image.new("RGBA", (fw * ss, fh * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    skin, hair = _rgb(look["skin"]), _rgb(look["hair"])
    outfit, accent = _rgb(look["outfit"]), _rgb(look["accent"])
    pants = _shade(outfit, 0.55)
    seated = pose in ("working_seated", "meeting_seated", "resting")
    cx = fw / 2
    foot_y = fh * cfg["anchor"][1]

    def rect(x0: float, y0: float, x1: float, y1: float, fill: tuple[int, int, int]) -> None:
        d.rounded_rectangle([x0 * ss, y0 * ss, x1 * ss, y1 * ss], radius=2 * ss, fill=fill)

    def limb(x0: float, y0: float, x1: float, y1: float, fill: tuple[int, int, int], wd: float = 5) -> None:
        d.line([x0 * ss, y0 * ss, x1 * ss, y1 * ss], fill=fill, width=int(wd * ss))

    drop = 14 if seated else 0  # seated body sits lower
    hip_y = foot_y - 28 + drop
    torso_top = hip_y - 26
    head_cy = torso_top - 11

    # legs
    if seated:
        limb(cx - 5, hip_y, cx - 5, hip_y + 4, pants, 7)
        limb(cx + 5, hip_y, cx + 5, hip_y + 4, pants, 7)
        limb(cx - 5, hip_y + 3, cx - 7, hip_y + 18, pants, 6)  # thighs forward-down in iso view
        limb(cx + 5, hip_y + 3, cx + 7, hip_y + 18, pants, 6)
    else:
        step = {"walk_a": 4, "walk_b": -4}.get(pose, 0)
        limb(cx - 4, hip_y, cx - 4 - step, foot_y, pants, 6)
        limb(cx + 4, hip_y, cx + 4 + step, foot_y, pants, 6)
        rect(cx - 8 - step, foot_y - 2, cx - 1 - step, foot_y + 1, (30, 30, 36))
        rect(cx + 1 + step, foot_y - 2, cx + 8 + step, foot_y + 1, (30, 30, 36))
    # torso
    rect(cx - 9, torso_top, cx + 9, hip_y + 2, outfit)
    rect(cx - 9, hip_y - 4, cx + 9, hip_y, accent)  # belt / accent band
    # arms
    sh_y = torso_top + 4
    swing = {"walk_a": 5, "walk_b": -5}.get(pose, 0)
    if pose == "celebration":
        limb(cx - 9, sh_y, cx - 17, sh_y - 16, skin, 4)
        limb(cx + 9, sh_y, cx + 17, sh_y - 16, skin, 4)
    elif pose == "emergency":
        limb(cx - 9, sh_y, cx - 20, sh_y + 2, skin, 4)
        limb(cx + 9, sh_y, cx + 20, sh_y + 2, skin, 4)
    elif pose == "working_seated":
        limb(cx - 9, sh_y, cx - 12, sh_y + 12, skin, 4)
        limb(cx + 9, sh_y, cx + 12, sh_y + 12, skin, 4)
        limb(cx - 12, sh_y + 12, cx - 4, sh_y + 16, skin, 4)  # hands toward the keyboard
        limb(cx + 12, sh_y + 12, cx + 4, sh_y + 16, skin, 4)
    elif pose == "meeting_seated":
        limb(cx - 9, sh_y, cx - 12, sh_y + 12, skin, 4)
        limb(cx + 9, sh_y, cx + 15, sh_y - 8, skin, 4)  # raised hand: speaking
    elif pose == "resting":
        limb(cx - 9, sh_y, cx - 15, sh_y - 4, skin, 4)  # hands behind head
        limb(cx + 9, sh_y, cx + 15, sh_y - 4, skin, 4)
    else:
        limb(cx - 9, sh_y, cx - 11, sh_y + 16 + swing, skin, 4)
        limb(cx + 9, sh_y, cx + 11, sh_y + 16 - swing, skin, 4)
    # head + hair
    tilt = -2 if pose == "resting" else 0
    d.ellipse([(cx - 8 + tilt) * ss, (head_cy - 9) * ss, (cx + 8 + tilt) * ss, (head_cy + 8) * ss], fill=skin)
    style = look["style"]
    hx0, hx1 = (cx - 9 + tilt) * ss, (cx + 9 + tilt) * ss
    d.pieslice([hx0, (head_cy - 11) * ss, hx1, (head_cy + 7) * ss], 180, 360, fill=hair)
    if style == "long":
        rect(cx - 10 + tilt, head_cy - 4, cx - 6 + tilt, head_cy + 12, hair)
        rect(cx + 6 + tilt, head_cy - 4, cx + 10 + tilt, head_cy + 12, hair)
    elif style == "bun":
        d.ellipse([(cx - 4 + tilt) * ss, (head_cy - 17) * ss, (cx + 4 + tilt) * ss, (head_cy - 10) * ss], fill=hair)
    elif style == "cap":
        rect(cx - 9 + tilt, head_cy - 8, cx + 9 + tilt, head_cy - 4, accent)
        rect(cx - 2 + tilt, head_cy - 5, cx + 12 + tilt, head_cy - 3, accent)
    d.ellipse([(cx - 4 + tilt) * ss, (head_cy - 1) * ss, (cx - 2 + tilt) * ss, (head_cy + 1) * ss], fill=(25, 25, 30))
    d.ellipse([(cx + 2 + tilt) * ss, (head_cy - 1) * ss, (cx + 4 + tilt) * ss, (head_cy + 1) * ss], fill=(25, 25, 30))
    if pose == "emergency":  # red "!" so the state reads even when small
        rect(cx - 1.5, head_cy - 30, cx + 1.5, head_cy - 20, (239, 68, 68))
        d.ellipse([(cx - 1.8) * ss, (head_cy - 18) * ss, (cx + 1.8) * ss, (head_cy - 14.4) * ss], fill=(239, 68, 68))
    return img.resize((fw, fh), Image.LANCZOS)


def _draw_character_sheet(spec: dict[str, Any], look: dict[str, str]) -> Image.Image:
    cfg = spec["character"]
    poses = cfg["poses"]
    sheet = Image.new("RGBA", (cfg["frameWidth"] * len(poses), cfg["frameHeight"]), (0, 0, 0, 0))
    for i, pose in enumerate(poses):
        sheet.paste(_draw_character(spec, look, pose), (i * cfg["frameWidth"], 0))
    return sheet


# --------------------------------------------------------------------------
# Output assembly
# --------------------------------------------------------------------------


def _png_bytes(img: Image.Image) -> bytes:
    import io

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=False, compress_level=9)
    return buf.getvalue()


def build_outputs(spec: dict[str, Any] | None = None) -> dict[str, bytes]:
    """Return ``{absolute_path: bytes}`` for every file this generator owns."""
    spec = spec or _load(SPEC_PATH)
    out: dict[str, bytes] = {}
    iso_block: dict[str, Any] = {
        "version": spec["version"],
        "tile": spec["tile"],
        "character": {
            "frameWidth": spec["character"]["frameWidth"],
            "frameHeight": spec["character"]["frameHeight"],
            "anchor": spec["character"]["anchor"],
            "poses": spec["character"]["poses"],
            "behaviorPose": spec["character"]["behaviorPose"],
            "seatedWorkingPose": spec["character"]["seatedWorkingPose"],
        },
        "props": {},
        "npc": {},
        "assetIds": {},
    }
    for prop in spec["props"]:
        img, anchor = _draw_prop(spec, prop)
        rel = f"iso/props/{prop['key']}.png"
        out[os.path.join(FRONTEND_ASSETS, rel)] = _png_bytes(img)
        iso_block["props"][prop["key"]] = {
            "path": f"/assets/world/{rel}",
            "width": img.width,
            "height": img.height,
            "anchor": anchor,
            "footprint": prop["footprint"],
            "heightPx": prop["height"],
        }
        iso_block["assetIds"][prop["id"]] = prop["key"]
    for cid, look in sorted(spec["looks"].items()):
        rel = f"iso/npc/{cid}.png"
        out[os.path.join(FRONTEND_ASSETS, rel)] = _png_bytes(_draw_character_sheet(spec, look))
        iso_block["npc"][cid] = f"/assets/world/{rel}"

    manifest = _load(FRONTEND_MANIFEST)
    manifest["iso"] = iso_block
    out[FRONTEND_MANIFEST] = _dump(FRONTEND_MANIFEST, manifest, indent=2)
    out.update(_backend_catalog_outputs(spec))
    return out


def _backend_catalog_outputs(spec: dict[str, Any]) -> dict[str, bytes]:
    """Additive, idempotent backend catalog entries. Existing entries are never edited."""
    out: dict[str, bytes] = {}
    char_ids = sorted(spec["looks"])
    new_furniture = [p for p in spec["props"] if p.get("newFurniture")]

    manifest_path = os.path.join(DATA_DIR, "asset_manifest.json")
    manifest = _load(manifest_path)
    have = {e["id"] for e in manifest}

    def entry(asset_id: str, category: str, tags: list[str]) -> dict[str, Any]:
        return {
            "id": asset_id, "category": category, "source": "custom", "tags": tags,
            "variants": [], "dependencies": [], "version": "1.0.0",
            "compatibleWith": ["pixijs", "phaser", "godot", "unity", "react"],
        }

    for cid in char_ids:
        for state in NEW_CHARACTER_STATES:
            aid = f"sprite.{cid}.{state}"
            if aid not in have:
                manifest.append(entry(aid, "character-sprite", ["character", cid, state, "isometric"]))
    for p in new_furniture:
        if p["id"] not in have:
            name = p["id"].split(".", 1)[1]
            manifest.append(entry(p["id"], "furniture", ["furniture", name, "isometric"]))
    out[manifest_path] = _dump(manifest_path, manifest)

    ca_path = os.path.join(DATA_DIR, "character_assets.json")
    chars = _load(ca_path)
    for c in chars:
        for state in NEW_CHARACTER_STATES:
            c["spriteAssetIds"].setdefault(state, f"sprite.{c['characterId']}.{state}")
    out[ca_path] = _dump(ca_path, chars)

    fa_path = os.path.join(DATA_DIR, "furniture_assets.json")
    furniture = _load(fa_path)
    have_f = {f["id"] for f in furniture}
    for p in new_furniture:
        if p["id"] not in have_f:
            furniture.append({
                "id": p["id"], "name": p["newFurniture"], "manifestId": p["id"],
                "footprint": {"width": float(p["footprint"][0]), "height": float(p["footprint"][1])},
                "interactable": False, "defaultInteractions": [],
            })
    out[fa_path] = _dump(fa_path, furniture)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated file would change")
    args = ap.parse_args(argv)
    outputs = build_outputs()
    stale = []
    for path, data in outputs.items():
        current = open(path, "rb").read() if os.path.isfile(path) else None
        if current != data:
            stale.append(path)
            if not args.check:
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
    verb = "stale" if args.check else "written"
    print(f"generate_iso_assets: {len(stale)} file(s) {verb}, {len(outputs)} total")
    return 1 if (args.check and stale) else 0


if __name__ == "__main__":
    sys.exit(main())
