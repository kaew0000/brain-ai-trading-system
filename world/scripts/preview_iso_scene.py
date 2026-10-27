"""Compose a preview of the isometric office from the generated assets (W-ISO-3).

Usage: python -m world.scripts.preview_iso_scene [out.png]
Not part of the asset pipeline (output is a convenience image, not asserted by tests).
"""

from __future__ import annotations

import json
import os
import sys

from PIL import Image

from world.scripts import generate_iso_assets as gen

TW, TH = 64, 32


def _load(rel: str) -> Image.Image:
    return Image.open(os.path.join(gen.FRONTEND_ASSETS, rel.replace("/assets/world/", ""))).convert("RGBA")


def render(size: tuple[int, int] = (1280, 760), n: int = 10) -> Image.Image:
    iso = json.load(open(gen.FRONTEND_MANIFEST, encoding="utf-8"))["iso"]
    canvas = Image.new("RGBA", size, (236, 240, 236, 255))
    ox, oy = size[0] // 2, 120

    def sp(gx: float, gy: float) -> tuple[float, float]:
        return ox + (gx - gy) * TW / 2, oy + (gx + gy) * TH / 2

    tile = _load(iso["tiles"]["floor_light"])
    wood = _load(iso["tiles"]["floor_wood"])
    carpet = _load(iso["tiles"]["floor_carpet"])
    for gx in range(n):
        for gy in range(n):
            t = wood if (gx >= 6 and gy <= 3) else carpet if (gx <= 3 and gy >= 6) else tile
            x, y = sp(gx, gy)
            canvas.alpha_composite(t, (int(x - TW / 2), int(y)))

    items: list[tuple[float, Image.Image, tuple[float, float]]] = []

    def prop(key: str, gx: float, gy: float) -> None:
        e = iso["props"][key]
        img = _load(e["path"])
        a, b = e["footprint"]
        x, y = sp(gx + a / 2, gy + b / 2)
        pos = (x - e["anchor"][0] * e["width"], y - e["anchor"][1] * e["height"])
        items.append((gx + a + gy + b, img, pos))

    def char(cid: str, gx: float, gy: float, frame: int = 0, row: int | None = None) -> None:
        c = iso["character"]
        fw, fh = c["frameWidth"], c["frameHeight"]
        if row is None:
            sheet = _load(iso["npc"][cid])
            fr = sheet.crop((frame * fw, 0, (frame + 1) * fw, fh))
        else:
            sheet = _load(iso["walk"]["sheets"][cid])
            fr = sheet.crop((frame * fw, row * fh, (frame + 1) * fw, (row + 1) * fh))
        x, y = sp(gx, gy)
        items.append((gx + gy + 0.4, fr, (x - c["anchor"][0] * fw, y - c["anchor"][1] * fh)))

    prop("rug", 0, 6)
    prop("glass_wall_x", 0, 0); prop("glass_wall_x", 3, 0); prop("glass_wall_x", 6, 0)
    prop("glass_wall_y", 0, 1); prop("glass_wall_y", 0, 4)
    prop("whiteboard", 1, 1)
    prop("market_board", 5, 0.2)
    prop("bookshelf", 8, 0.2)
    prop("workstation_pod", 2, 3)
    prop("workstation_pod", 6, 5)
    prop("workstation", 6, 1.6)
    for gx, gy in ((2.3, 2.6), (3.3, 2.6), (2.3, 5.1), (3.3, 5.1), (6.3, 4.6), (7.3, 4.6), (6.3, 7.1), (7.3, 7.1), (6.3, 2.6)):
        prop("chair", gx, gy)
    prop("sofa", 1, 7.2); prop("meeting_table", 3.5, 7.3)
    prop("plant_large", 0.3, 5.3); prop("plant", 9, 3); prop("coffee_machine", 9, 6); prop("water_cooler", 9, 7.2)
    prop("printer", 9, 8.4); prop("server_rack", 9, 0.3)
    char("primus", 2.8, 2.9, 3); char("oracle", 3.8, 2.9, 3); char("sentinel", 6.8, 4.9, 3)
    char("echo", 4, 8.0, 4); char("scribe", 5.2, 8.0, 4)
    char("forge", 5, 5, 1, row=0); char("chameleon", 4.6, 4.2, 2, row=1)
    char("herald", 8, 3.2, 1, row=2); char("watcher", 1.6, 5, 3, row=3)
    char("phoenix", 7, 9, 6); char("crucible", 8.2, 5.1, 7)
    for _, img, pos in sorted(items, key=lambda t: t[0]):
        canvas.alpha_composite(img, (int(pos[0]), int(pos[1])))
    return canvas


if __name__ == "__main__":
    from PIL import ImageChops

    out = sys.argv[1] if len(sys.argv) > 1 else "iso_preview.png"
    img = render().convert("RGB")
    bg = Image.new("RGB", img.size, (236, 240, 236))
    box = ImageChops.difference(img, bg).getbbox() or (0, 0, *img.size)
    box = (max(0, box[0] - 24), max(0, box[1] - 24), min(img.width, box[2] + 24), min(img.height, box[3] + 24))
    img = img.crop(box)
    img.resize((img.width * 2, img.height * 2), Image.LANCZOS).save(out)
    print(out)
