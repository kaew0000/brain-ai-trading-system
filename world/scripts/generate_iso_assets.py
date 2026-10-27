"""Deterministic generator for the Office World isometric art (W-ISO-2 / W-ISO-3).

Single source of truth: ``world/data/assets/iso_assets.json`` (tile size,
prop footprints/heights, per-character look, pose list). This script turns
that spec into:

* ``dashboard_src/public/assets/world/iso/props/<key>.png``
* ``dashboard_src/public/assets/world/iso/npc/<character>.png`` (one row of
  pose frames; frame order == ``character.poses`` in the spec)
* ``.../iso/npc_walk/<character>.png`` (W-ISO-3: rows = ``walk.directions``,
  cols = ``walk.frames``)
* ``.../iso/tiles/<tile>.png`` (W-ISO-3: 64x32 floor diamonds)
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

try:  # Pillow is only needed to draw; importing this module (paths, constants) must not require it.
    from PIL import Image
    from world.scripts import iso_art
except ImportError:  # pragma: no cover - exercised only where Pillow is absent
    Image = iso_art = None  # type: ignore[assignment]

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
    if Image is None:
        raise RuntimeError("Pillow is required to generate isometric assets: pip install pillow")
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
        # W-ISO-3 (additive): 4-direction walk strips + floor tiles. Older clients ignore these keys.
        "walk": {
            "frameWidth": spec["character"]["frameWidth"],
            "frameHeight": spec["character"]["frameHeight"],
            "directions": spec["character"]["walk"]["directions"],
            "frames": spec["character"]["walk"]["frames"],
            "fps": spec["character"]["walk"]["fps"],
            "sheets": {},
        },
        "tiles": {},
    }
    for prop in spec["props"]:
        img, anchor = iso_art.draw_prop(spec, prop)
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
        for alias in prop.get("aliases", []):  # other backend ids that should reuse this art
            iso_block["assetIds"][alias] = prop["key"]
    for cid, look in sorted(spec["looks"].items()):
        rel = f"iso/npc/{cid}.png"
        out[os.path.join(FRONTEND_ASSETS, rel)] = _png_bytes(iso_art.draw_character_sheet(spec, look))
        iso_block["npc"][cid] = f"/assets/world/{rel}"
        wrel = f"iso/npc_walk/{cid}.png"
        out[os.path.join(FRONTEND_ASSETS, wrel)] = _png_bytes(iso_art.draw_walk_sheet(spec, look))
        iso_block["walk"]["sheets"][cid] = f"/assets/world/{wrel}"
    for tile in spec["tiles"]:
        trel = f"iso/tiles/{tile['key']}.png"
        out[os.path.join(FRONTEND_ASSETS, trel)] = _png_bytes(iso_art.draw_tile(spec, tile))
        iso_block["tiles"][tile["key"]] = f"/assets/world/{trel}"

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
