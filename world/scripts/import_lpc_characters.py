"""Import Universal-LPC character exports into the Office World (V16 §93).

Input: a directory (or .zip) holding one sub-folder per character, each with the generator's
``*.png`` spritesheet, ``*.json`` selection file and ``credits*.csv``. The folder -> NPC role
mapping, the sheet layout and the behaviour -> animation table live in
``world/data/assets/lpc_characters.json`` (nothing is hard-coded here).

Writes (all additive):

* ``dashboard_src/public/assets/world/lpc/<role>.png`` - normalised sheet names
* ``dashboard_src/public/third-party-licenses/lpc_credits.csv`` - merged, de-duplicated credits
* the ``lpc`` block of ``dashboard_src/public/assets/world/manifest.json`` (other keys untouched)

``unsupportedAnimations`` is derived from each export's JSON: a clothing layer that does not
support an animation (for example a tunic without ``sit``) makes that animation render with a
missing garment, so the scene falls back for that role.

Usage: ``python -m world.scripts.import_lpc_characters <dir-or-zip>``
"""
from __future__ import annotations

import csv
import glob
import io
import json
import os
import sys
import tempfile
import zipfile
from typing import Any

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(WORLD_ROOT)
SPEC_PATH = os.path.join(WORLD_ROOT, "data", "assets", "lpc_characters.json")
FRONTEND_ASSETS = os.path.join(REPO_ROOT, "dashboard_src", "public", "assets", "world")
FRONTEND_MANIFEST = os.path.join(FRONTEND_ASSETS, "manifest.json")
LPC_DIR = os.path.join(FRONTEND_ASSETS, "lpc")
CREDITS_PATH = os.path.join(REPO_ROOT, "dashboard_src", "public", "third-party-licenses", "lpc_credits.csv")
CREDITS_HEADER = ["filename", "notes", "authors", "licenses", "urls"]


def _load(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _one(folder: str, pattern: str) -> str:
    hits = sorted(glob.glob(os.path.join(folder, pattern)))
    if len(hits) != 1:
        raise ValueError(f"{folder}: expected exactly one {pattern}, found {len(hits)}")
    return hits[0]


def unsupported_animations(selection: dict[str, Any], animations: dict[str, dict[str, Any]]) -> list[str]:
    """Spec animation names whose LPC ``source`` animation at least one selected layer does not support."""
    missing: set[str] = set()
    for layer in selection.get("layers", []):
        supported = set(layer.get("supportedAnimations", []))
        missing.update(name for name, anim in animations.items() if anim["source"] not in supported)
    return sorted(missing)


def build_lpc_block(spec: dict[str, Any], source_root: str) -> tuple[dict[str, Any], dict[str, str], list[list[str]]]:
    """Returns (manifest block, {role: source png path}, merged credit rows)."""
    block = {k: v for k, v in spec.items() if k != "sourceFolders"}
    sheets: dict[str, str] = {}
    sources: dict[str, str] = {}
    unsupported: dict[str, list[str]] = {}
    credits: dict[str, list[str]] = {}
    for folder_name, role in sorted(spec["sourceFolders"].items(), key=lambda kv: kv[1]):
        folder = os.path.join(source_root, folder_name)
        if not os.path.isdir(folder):
            raise ValueError(f"missing character folder: {folder_name}")
        sources[role] = _one(folder, "*.png")
        sheets[role] = f"/assets/world/lpc/{role}.png"
        bad = unsupported_animations(_load(_one(folder, "*.json")), spec["animations"])
        if bad:
            unsupported[role] = bad
        with open(_one(folder, "credits*.csv"), encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                credits.setdefault(row["filename"], [row.get(c, "") for c in CREDITS_HEADER])
    block["sheets"] = sheets
    block["unsupportedAnimations"] = unsupported
    return block, sources, [credits[k] for k in sorted(credits)]


def run(source: str) -> None:
    from PIL import Image  # local import: Pillow is only needed for the import tool

    spec = _load(SPEC_PATH)
    with tempfile.TemporaryDirectory() as tmp:
        root = source
        if source.lower().endswith(".zip"):
            with zipfile.ZipFile(source) as zf:
                zf.extractall(tmp)
            entries = [d for d in os.listdir(tmp) if os.path.isdir(os.path.join(tmp, d))]
            root = os.path.join(tmp, entries[0]) if len(entries) == 1 else tmp
        block, sources, credits = build_lpc_block(spec, root)
        want = (spec["columns"] * spec["frameSize"], spec["rows"] * spec["frameSize"])
        os.makedirs(LPC_DIR, exist_ok=True)
        for role, src in sources.items():
            with Image.open(src) as im:
                if im.size != want:
                    raise ValueError(f"{src}: sheet is {im.size}, expected {want}")
            with open(src, "rb") as fin, open(os.path.join(LPC_DIR, f"{role}.png"), "wb") as fout:
                fout.write(fin.read())
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(CREDITS_HEADER)
    writer.writerows(credits)
    os.makedirs(os.path.dirname(CREDITS_PATH), exist_ok=True)
    with open(CREDITS_PATH, "w", encoding="utf-8", newline="") as f:
        f.write(buf.getvalue())
    manifest = _load(FRONTEND_MANIFEST)
    manifest["lpc"] = block
    with open(FRONTEND_MANIFEST, "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
        f.write("\n")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    run(sys.argv[1])
