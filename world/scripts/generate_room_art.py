"""Deterministic generator for the Office World room backdrops (V16 §92).

Single source of truth: ``world/data/assets/room_art.json`` (canvas size, palette,
room list). Turns that spec into:

* ``dashboard_src/public/assets/world/buildings/<key>.png`` - pixel-art facades in
  the same family as the existing ``buildings/*.png`` (steel frame, gold neon
  sign plate, cyan door), for the rooms that previously had no art of their own:
  ``lobby``, ``hallway``, ``elevator`` (no district exists for them, so
  ``OfficeScene`` looks them up by room id) and ``recovery_center``,
  ``journal_library``, ``training_arena`` (previously mapped to the whole
  ``buildings_sheet`` / unrelated facades).
* the ``buildings`` block of ``dashboard_src/public/assets/world/manifest.json``
  (additive: existing keys are never touched; the ``iso`` block belongs to
  ``generate_iso_assets`` and is passed through unchanged).

Pure drawing code - no randomness, no network, no third-party art - so
re-running it is a no-op on a clean checkout (asserted by
``world/tests/test_room_art.py``).

Usage: ``python -m world.scripts.generate_room_art [--check]``
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

try:  # Pillow is only needed to draw; importing this module (paths) must not require it.
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - exercised only where Pillow is absent
    Image = ImageDraw = None  # type: ignore[assignment]

from world.scripts.generate_iso_assets import FRONTEND_ASSETS, FRONTEND_MANIFEST, DATA_DIR, _dump, _load, _png_bytes
from world.scripts.iso_art import mix, rgb, shade

SPEC_PATH = os.path.join(DATA_DIR, "room_art.json")
BUILDINGS_DIR = os.path.join(FRONTEND_ASSETS, "buildings")
BUILDINGS_URL_PREFIX = "/assets/world/buildings/"

RGB = tuple[int, int, int]

# 5x7 pixel font: only the glyphs the room labels need (validated in build_outputs).
_GLYPHS: dict[str, tuple[str, ...]] = {
    "A": ("01110", "10001", "10001", "11111", "10001", "10001", "10001"),
    "B": ("11110", "10001", "10001", "11110", "10001", "10001", "11110"),
    "C": ("01111", "10000", "10000", "10000", "10000", "10000", "01111"),
    "E": ("11111", "10000", "10000", "11110", "10000", "10000", "11111"),
    "G": ("01111", "10000", "10000", "10011", "10001", "10001", "01111"),
    "H": ("10001", "10001", "10001", "11111", "10001", "10001", "10001"),
    "I": ("11111", "00100", "00100", "00100", "00100", "00100", "11111"),
    "J": ("00111", "00010", "00010", "00010", "00010", "10010", "01100"),
    "L": ("10000", "10000", "10000", "10000", "10000", "10000", "11111"),
    "N": ("10001", "11001", "10101", "10101", "10011", "10001", "10001"),
    "O": ("01110", "10001", "10001", "10001", "10001", "10001", "01110"),
    "R": ("11110", "10001", "10001", "11110", "10100", "10010", "10001"),
    "T": ("11111", "00100", "00100", "00100", "00100", "00100", "00100"),
    "U": ("10001", "10001", "10001", "10001", "10001", "10001", "01110"),
    "V": ("10001", "10001", "10001", "10001", "10001", "01010", "00100"),
    "W": ("10001", "10001", "10001", "10101", "10101", "11011", "10001"),
    "Y": ("10001", "10001", "01010", "00100", "00100", "00100", "00100"),
    " ": ("00000",) * 7,
}
GLYPH_W, GLYPH_H, GLYPH_GAP = 5, 7, 1

# Layout proportions of the shared facade shell (fractions of the canvas / px offsets).
SIGN_X0, SIGN_X1 = 0.12, 0.88
SIGN_Y0, SIGN_Y1 = 9, 37
BASE_HEIGHT = 50
CUT = 10  # chamfered top corners


def _palette(spec: dict[str, Any]) -> dict[str, RGB]:
    return {name: rgb(value) for name, value in spec["palette"].items()}


class _Pen:
    """Tiny helper: a draw handle plus the room palette, so scene code stays short."""

    def __init__(self, img: Image.Image, pal: dict[str, RGB]) -> None:
        self.img = img
        self.d = ImageDraw.Draw(img)
        self.p = pal

    def rect(self, x0: int, y0: int, x1: int, y1: int, fill: RGB, outline: RGB | None = None) -> None:
        self.d.rectangle([x0, y0, x1, y1], fill=fill, outline=outline if outline is not None else None)

    def glow(self, x0: int, y0: int, x1: int, y1: int, col: RGB, alpha: int = 70, grow: int = 2) -> None:
        layer = Image.new("RGBA", self.img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).rectangle([x0 - grow, y0 - grow, x1 + grow, y1 + grow], fill=col + (alpha,))
        self.img.alpha_composite(layer)
        self.d = ImageDraw.Draw(self.img)

    def text(self, x: int, y: int, label: str, fill: RGB, shadow: RGB | None, scale: int) -> None:
        cx = x
        for ch in label:
            rows = _GLYPHS[ch]
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        if shadow is not None:
                            self.d.rectangle([cx + rx * scale + 1, y + ry * scale + 1, cx + rx * scale + scale, y + ry * scale + scale], fill=shadow)
                        self.d.rectangle([cx + rx * scale, y + ry * scale, cx + rx * scale + scale - 1, y + ry * scale + scale - 1], fill=fill)
            cx += (GLYPH_W + GLYPH_GAP) * scale


def _text_width(label: str, scale: int) -> int:
    return len(label) * (GLYPH_W + GLYPH_GAP) * scale - GLYPH_GAP * scale


def _shell(pen: _Pen, w: int, h: int, label: str, door: bool) -> tuple[int, int, int, int]:
    """Steel frame + gold sign plate + base strip (+ cyan door). Returns the free scene box (x0, y0, x1, y1)."""
    p, d = pen.p, pen.d
    body = [(4 + CUT, 4), (w - 5 - CUT, 4), (w - 5, 4 + CUT), (w - 5, h - 2), (4, h - 2), (4, 4 + CUT)]
    d.polygon(body, fill=p["steel_dark"], outline=p["outline"])
    d.rectangle([10, 14, w - 11, h - 3], fill=p["steel"], outline=p["steel_dark"])
    for x in (10, w - 11):  # vertical ribs
        d.line([(x, 14), (x, h - 3)], fill=p["steel_light"])
    for y in (46, 82, 118):  # panel seams
        d.line([(11, y), (w - 12, y)], fill=shade(p["steel"], 0.82))

    # gold neon sign plate with a soft two-step glow
    x0, x1 = int(w * SIGN_X0), int(w * SIGN_X1)
    pen.glow(x0, SIGN_Y0, x1, SIGN_Y1, p["gold"], alpha=55, grow=3)
    pen.glow(x0, SIGN_Y0, x1, SIGN_Y1, p["gold"], alpha=90, grow=1)
    d = pen.d
    d.rectangle([x0, SIGN_Y0, x1, SIGN_Y1], fill=shade(p["outline"], 1.0), outline=p["gold"], width=2)
    scale = 2
    tx = x0 + ((x1 - x0) - _text_width(label, scale)) // 2
    ty = SIGN_Y0 + ((SIGN_Y1 - SIGN_Y0) - GLYPH_H * scale) // 2 + 1
    pen.text(tx, ty, label, p["gold"], p["text_shadow"], scale)

    # base strip
    base_y = h - BASE_HEIGHT
    d.rectangle([11, base_y, w - 12, h - 3], fill=p["steel_light"], outline=p["outline"])
    d.line([(12, base_y + 1), (w - 13, base_y + 1)], fill=mix(p["steel_light"], (255, 255, 255), 0.18))
    if door:
        cx = w // 2
        d.rectangle([cx - 26, base_y - 6, cx + 26, h - 3], fill=p["steel_dark"], outline=p["outline"])
        d.rectangle([cx - 20, base_y - 1, cx + 20, h - 3], fill=p["cyan"], outline=p["outline"])
        d.line([(cx, base_y - 1), (cx, h - 3)], fill=p["outline"], width=2)
        d.rectangle([cx - 18, base_y + 1, cx - 3, base_y + 6], fill=mix(p["cyan"], (255, 255, 255), 0.35))
        d.rectangle([cx + 3, base_y + 1, cx + 18, base_y + 6], fill=mix(p["cyan"], (255, 255, 255), 0.35))
        for sx in (cx - 82, cx + 40):  # side windows
            d.rectangle([sx, base_y + 10, sx + 42, base_y + 28], fill=p["cyan"], outline=p["outline"])
            d.rectangle([sx + 2, base_y + 12, sx + 40, base_y + 16], fill=mix(p["cyan"], (255, 255, 255), 0.3))
    return 18, SIGN_Y1 + 8, w - 18, base_y - 8


# --------------------------------------------------------------------------
# Scenes (each draws inside the box returned by _shell)
# --------------------------------------------------------------------------


def _screen(pen: _Pen, x0: int, y0: int, x1: int, y1: int, glow: RGB) -> None:
    p = pen.p
    pen.rect(x0 - 2, y0 - 2, x1 + 2, y1 + 2, p["steel_dark"], p["outline"])
    pen.rect(x0, y0, x1, y1, p["screen"], shade(glow, 0.55))


def _chamfer(pen: _Pen, x0: int, y0: int, x1: int, y1: int, c: int, fill: RGB, outline: RGB) -> None:
    """Pixel-art rounded box: a chamfered polygon. Unlike ``rounded_rectangle`` its rasterisation does not vary between Pillow releases."""
    pts = [(x0 + c, y0), (x1 - c, y0), (x1, y0 + c), (x1, y1 - c), (x1 - c, y1), (x0 + c, y1), (x0, y1 - c), (x0, y0 + c)]
    pen.d.polygon(pts, fill=fill, outline=outline)


def _plant(pen: _Pen, cx: int, base: int) -> None:
    p = pen.p
    pen.rect(cx - 5, base - 8, cx + 5, base, shade(p["gold_dark"], 0.9), p["outline"])
    for dx, dy, r in ((0, -20, 8), (-7, -14, 6), (7, -14, 6), (0, -12, 6)):
        pen.d.ellipse([cx + dx - r, base + dy - r, cx + dx + r, base + dy + r], fill=shade(p["green"], 0.7), outline=shade(p["green"], 0.4))


def _scene_lobby(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    d.ellipse([cx - 24, y0 + 4, cx + 24, y0 + 52], outline=p["cyan"], width=2)  # wall logo ring
    d.ellipse([cx - 14, y0 + 14, cx + 14, y0 + 42], outline=shade(p["cyan"], 0.6), width=1)
    for ax, ay in ((cx - 7, y0 + 24), (cx + 4, y0 + 20), (cx - 2, y0 + 33), (cx + 8, y0 + 31)):
        pen.rect(ax, ay, ax + 2, ay + 2, p["cyan"])
    pen.rect(cx - 46, y1 - 22, cx + 46, y1 + 4, p["steel_dark"], p["outline"])  # reception desk
    pen.rect(cx - 46, y1 - 22, cx + 46, y1 - 18, p["steel_light"], p["outline"])
    pen.rect(cx - 12, y1 - 14, cx + 12, y1 - 6, p["screen"], p["cyan_dark"])
    _plant(pen, x0 + 14, y1 + 4)
    _plant(pen, x1 - 14, y1 + 4)
    for lx in (x0 + 40, x1 - 40):  # wall lamps
        pen.glow(lx - 4, y0 + 2, lx + 4, y0 + 10, p["amber"], alpha=70, grow=2)
        pen.rect(lx - 4, y0 + 2, lx + 4, y0 + 10, p["amber"], p["outline"])


def _scene_hallway(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    bx0, bx1, by0, by1 = cx - 26, cx + 26, y0 + 12, y1 - 22  # far wall
    d.polygon([(x0, y0), (x1, y0), (bx1, by0), (bx0, by0)], fill=shade(p["steel_dark"], 0.9))  # ceiling
    d.polygon([(x0, y1 + 6), (x1, y1 + 6), (bx1, by1), (bx0, by1)], fill=shade(p["steel_light"], 0.9))  # floor
    d.polygon([(x0, y0), (bx0, by0), (bx0, by1), (x0, y1 + 6)], fill=p["steel"])  # left wall
    d.polygon([(x1, y0), (bx1, by0), (bx1, by1), (x1, y1 + 6)], fill=p["steel"])  # right wall
    pen.rect(bx0, by0, bx1, by1, p["screen"], p["cyan_dark"])  # far end opening
    pen.rect(bx0 + 8, by0 + 6, bx1 - 8, by1, shade(p["cyan"], 0.5), p["cyan_dark"])
    d.line([(cx, by1), (cx, y1 + 6)], fill=p["cyan_dark"], width=2)  # floor guide line
    for i, (lw, ly) in enumerate(((22, y0 + 2), (14, y0 + 9), (8, by0 + 1))):  # ceiling lights, perspective
        pen.glow(cx - lw, ly, cx + lw, ly + 3, p["gold"], alpha=50, grow=2)
        pen.rect(cx - lw, ly, cx + lw, ly + 3, p["gold"], None)
    for side, sx in ((-1, x0 + 8), (1, x1 - 8)):  # doors along both walls, shrinking toward the end
        for k, (dw, dh, dy) in enumerate(((16, 46, y0 + 16), (10, 30, y0 + 24))):
            dx = sx + side * -k * 22
            pen.rect(dx - dw // 2, dy, dx + dw // 2, dy + dh, shade(p["cyan_dark"], 0.9), p["outline"])
            pen.rect(dx - dw // 2 + 2, dy + 3, dx + dw // 2 - 2, dy + 8, p["cyan"], None)


def _scene_elevator(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    pen.rect(cx - 22, y0 - 2, cx + 22, y0 + 10, p["screen"], p["cyan_dark"])  # floor indicator
    for i, on in enumerate((1, 0, 1, 1, 0)):
        pen.rect(cx - 18 + i * 8, y0 + 2, cx - 13 + i * 8, y0 + 7, p["cyan"] if on else shade(p["cyan_dark"], 0.5))
    dx0, dx1, dy0, dy1 = cx - 46, cx + 46, y0 + 16, y1 + 6
    pen.rect(dx0 - 3, dy0 - 3, dx1 + 3, dy1 + 3, p["steel_dark"], p["outline"])  # door frame
    for ax0, ax1 in ((dx0, cx - 1), (cx + 1, dx1)):  # brushed metal leaves
        pen.rect(ax0, dy0, ax1, dy1, mix(p["steel_light"], (200, 214, 230), 0.25), p["outline"])
        for gy in range(dy0 + 4, dy1, 6):
            d.line([(ax0 + 2, gy), (ax1 - 2, gy)], fill=mix(p["steel_light"], (200, 214, 230), 0.12))
    d.line([(cx, dy0), (cx, dy1)], fill=p["outline"], width=2)
    pen.rect(x1 - 20, y0 + 24, x1 - 8, y0 + 52, p["steel_dark"], p["outline"])  # call panel
    d.polygon([(x1 - 14, y0 + 28), (x1 - 18, y0 + 34), (x1 - 10, y0 + 34)], fill=p["cyan"])
    d.polygon([(x1 - 14, y0 + 48), (x1 - 18, y0 + 42), (x1 - 10, y0 + 42)], fill=p["amber"])
    for lx in (x0 + 12, x0 + 22):  # status lights
        pen.rect(lx, y0 + 30, lx + 4, y0 + 34, p["green"], p["outline"])


def _scene_recovery(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    for px in (x0 + 8, x1 - 46):  # recovery pods
        pen.glow(px, y0 + 4, px + 38, y1 + 4, p["green"], alpha=40, grow=3)
        pen.rect(px, y0 + 4, px + 38, y1 + 4, p["steel_dark"], p["outline"])
        _chamfer(pen, px + 5, y0 + 9, px + 33, y1 - 2, 6, shade(p["green"], 0.45), p["green"])
        _chamfer(pen, px + 9, y0 + 13, px + 17, y0 + 40, 2, mix(p["green"], (255, 255, 255), 0.4), mix(p["green"], (255, 255, 255), 0.4))
        pen.rect(px + 12, y1 - 8, px + 26, y1 - 4, p["cyan"], p["outline"])
    _screen(pen, cx - 34, y0 + 4, cx + 34, y0 + 52, p["green"])
    d.line([(cx - 30, y0 + 40), (cx - 18, y0 + 40), (cx - 14, y0 + 24), (cx - 8, y0 + 46), (cx - 2, y0 + 30), (cx + 4, y0 + 40), (cx + 30, y0 + 40)], fill=p["green"], width=1)
    pen.rect(cx - 3, y0 + 8, cx + 3, y0 + 18, p["green"])  # medical cross
    pen.rect(cx - 8, y0 + 12, cx + 8, y0 + 14, p["green"])
    pen.rect(cx - 30, y1 - 14, cx + 30, y1 + 4, p["steel_dark"], p["outline"])  # console
    for i in range(6):
        pen.rect(cx - 26 + i * 9, y1 - 10, cx - 21 + i * 9, y1 - 6, (p["cyan"], p["green"], p["amber"])[i % 3])


_BOOK_COLORS = ("red", "amber", "cyan", "green", "violet")


def _shelf(pen: _Pen, x0: int, y0: int, x1: int, y1: int) -> None:
    p, d = pen.p, pen.d
    pen.rect(x0, y0, x1, y1, p["steel_dark"], p["outline"])
    for row, ry in enumerate(range(y0 + 3, y1 - 8, 16)):
        d.line([(x0 + 1, ry + 14), (x1 - 1, ry + 14)], fill=p["steel_light"])
        bx = x0 + 3
        i = row * 2
        while bx < x1 - 6:
            bw = 3 + (i * 5 % 3)
            bh = 9 + (i * 7 % 5)
            col = p[_BOOK_COLORS[i % len(_BOOK_COLORS)]]
            pen.rect(bx, ry + 14 - bh, bx + bw, ry + 13, shade(col, 0.75), p["outline"])
            bx += bw + 2
            i += 1


def _scene_library(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    _shelf(pen, x0 + 2, y0 + 2, x0 + 52, y1 + 4)
    _shelf(pen, x1 - 52, y0 + 2, x1 - 2, y1 + 4)
    _screen(pen, cx - 32, y0 + 6, cx + 32, y0 + 46, p["cyan"])
    for i, lw in enumerate((44, 52, 36, 48, 30)):  # text lines
        pen.rect(cx - 28, y0 + 11 + i * 7, cx - 28 + lw, y0 + 12 + i * 7, shade(p["cyan"], 0.7))
    pen.rect(cx - 28 + 30, y0 + 39, cx - 28 + 33, y0 + 42, p["cyan"])  # cursor
    pen.rect(cx - 30, y1 - 14, cx + 30, y1 + 4, p["steel_dark"], p["outline"])  # reading desk + open ledger
    pen.rect(cx - 18, y1 - 12, cx - 1, y1 - 4, mix(p["gold"], (255, 255, 255), 0.5), p["outline"])
    pen.rect(cx + 1, y1 - 12, cx + 18, y1 - 4, mix(p["gold"], (255, 255, 255), 0.5), p["outline"])


def _scene_training(pen: _Pen, box: tuple[int, int, int, int]) -> None:
    p, d = pen.p, pen.d
    x0, y0, x1, y1 = box
    cx = (x0 + x1) // 2
    for dx in (x0 + 24, x1 - 24):  # training dummies
        d.ellipse([dx - 7, y0 + 18, dx + 7, y0 + 32], fill=p["amber"], outline=p["outline"])
        pen.rect(dx - 9, y0 + 33, dx + 9, y0 + 62, shade(p["amber"], 0.7), p["outline"])
        pen.rect(dx - 2, y0 + 62, dx + 2, y1 + 4, p["steel_dark"], p["outline"])
    for r, col in ((28, p["red"]), (20, (240, 244, 250)), (12, p["red"]), (5, (240, 244, 250))):  # holo target
        d.ellipse([cx - r, y0 + 28 - r // 2, cx + r, y0 + 28 + r + r // 2 - r // 2], outline=col, width=2)
    pen.rect(cx - 52, y0 - 2, cx + 52, y0 + 6, p["screen"], p["cyan_dark"])  # scoreboard strip
    for i, frac in enumerate((0.9, 0.6, 0.35)):
        pen.rect(cx - 48 + i * 33, y0 + 1, cx - 48 + i * 33 + int(28 * frac), y0 + 3, (p["green"], p["amber"], p["red"])[i])
    for fx in range(x0 + 6, x1 - 4, 24):  # floor mat markings
        pen.rect(fx, y1 - 2, fx + 14, y1, shade(p["cyan"], 0.55))


_SCENES = {
    "lobby": _scene_lobby,
    "hallway": _scene_hallway,
    "elevator": _scene_elevator,
    "recovery": _scene_recovery,
    "library": _scene_library,
    "training": _scene_training,
}


def draw_room(spec: dict[str, Any], room: dict[str, Any]) -> Image.Image:
    w, h = spec["size"]
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    pen = _Pen(img, _palette(spec))
    box = _shell(pen, w, h, room["label"], bool(room["door"]))
    _SCENES[room["scene"]](pen, box)
    return img


# --------------------------------------------------------------------------
# Output assembly
# --------------------------------------------------------------------------


def build_outputs(spec: dict[str, Any] | None = None) -> dict[str, bytes]:
    """Every file this generator owns: absolute path -> exact bytes."""
    spec = spec or _load(SPEC_PATH)
    out: dict[str, bytes] = {}
    buildings: dict[str, str] = {}
    for room in spec["rooms"]:
        missing = {ch for ch in room["label"] if ch not in _GLYPHS}
        if missing:
            raise ValueError(f"room {room['key']!r}: no glyph for {sorted(missing)}")
        if room["scene"] not in _SCENES:
            raise ValueError(f"room {room['key']!r}: unknown scene {room['scene']!r}")
        out[os.path.join(BUILDINGS_DIR, f"{room['key']}.png")] = _png_bytes(draw_room(spec, room))
        buildings[room["key"]] = f"{BUILDINGS_URL_PREFIX}{room['key']}.png"
    manifest = _load(FRONTEND_MANIFEST)
    manifest["buildings"] = dict(sorted({**manifest["buildings"], **buildings}.items()))
    out[FRONTEND_MANIFEST] = _dump(FRONTEND_MANIFEST, manifest, indent=2)
    return out


def is_current(path: str, data: bytes) -> bool:
    """True if ``path`` holds ``data``. PNGs compare by decoded pixels, so a different zlib/Pillow build cannot cause a false 'stale'."""
    if not os.path.isfile(path):
        return False
    with open(path, "rb") as f:
        on_disk = f.read()
    if on_disk == data or not path.endswith(".png"):
        return on_disk == data
    import io

    a, b = Image.open(io.BytesIO(on_disk)).convert("RGBA"), Image.open(io.BytesIO(data)).convert("RGBA")
    return a.size == b.size and a.tobytes() == b.tobytes()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any generated file is stale; write nothing")
    args = ap.parse_args(argv)
    if Image is None:
        print("Pillow is required to draw the room art (pip install pillow)", file=sys.stderr)
        return 2
    outputs = build_outputs()
    stale = [p for p, data in outputs.items() if not is_current(p, data)]
    if args.check:
        for p in stale:
            print(f"stale: {os.path.relpath(p, os.path.dirname(FRONTEND_ASSETS))}")
        return 1 if stale else 0
    for p in stale:
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "wb") as f:
            f.write(outputs[p])
        print(f"wrote {os.path.relpath(p)}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
