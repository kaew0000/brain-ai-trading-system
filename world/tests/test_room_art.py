"""V16 §92: room backdrop art pipeline contract.

Pins that the generator is deterministic, that the committed PNGs/manifest match the
spec, and that every room the Office World can show has its own backdrop (the
frontend resolves ``lobby``/``hallway``/``elevator`` by room id and the other three
through ``DISTRICT_TO_BUILDING``).
"""

import json
import os
import re
import struct

import pytest

from world.scripts import generate_room_art as gen

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ASSET_MAPPING_TS = os.path.join(REPO_ROOT, "dashboard_src", "src", "pages", "world", "assetMapping.ts")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", head[16:24])


def test_generated_files_are_up_to_date():
    pytest.importorskip("PIL")
    stale = [p for p, data in gen.build_outputs().items() if not gen.is_current(p, data)]
    assert stale == [], f"run `python -m world.scripts.generate_room_art`: {stale}"


def test_generator_is_deterministic():
    pytest.importorskip("PIL")
    assert gen.build_outputs() == gen.build_outputs()


def test_every_spec_room_is_in_the_frontend_manifest_with_matching_size():
    spec = _load(gen.SPEC_PATH)
    buildings = _load(gen.FRONTEND_MANIFEST)["buildings"]
    for room in spec["rooms"]:
        url = buildings[room["key"]]
        assert url == f"/assets/world/buildings/{room['key']}.png"
        assert _png_size(os.path.join(gen.BUILDINGS_DIR, f"{room['key']}.png")) == tuple(spec["size"])


def test_existing_building_keys_are_untouched():
    """Additive only: the original 14 keys keep their original paths."""
    buildings = _load(gen.FRONTEND_MANIFEST)["buildings"]
    for key in ("buildings_sheet", "ceo_room", "command_center", "data_center", "futures_trading_lab",
                "intelligence_lab", "mission_board_center", "ml_lab", "portfolio_vault", "replay_theater",
                "research_facility", "risk_center", "server_room", "teleport_entrance"):
        assert buildings[key] == f"/assets/world/buildings/{key}.png"


def test_every_label_glyph_exists():
    for room in _load(gen.SPEC_PATH)["rooms"]:
        assert {c for c in room["label"] if c not in gen._GLYPHS} == set()


def test_art_is_not_blank_and_keeps_transparent_corners():
    pytest.importorskip("PIL")
    spec = _load(gen.SPEC_PATH)
    for room in spec["rooms"]:
        img = gen.draw_room(spec, room)
        assert img.getpixel((0, 0))[3] == 0
        assert img.getpixel((img.width - 1, 0))[3] == 0
        opaque = sum(1 for a in img.getchannel("A").tobytes() if a > 200)
        assert opaque > img.width * img.height * 0.5, room["key"]


def test_rooms_have_distinct_art():
    pytest.importorskip("PIL")
    spec = _load(gen.SPEC_PATH)
    blobs = [gen.draw_room(spec, room).tobytes() for room in spec["rooms"]]
    assert len(set(blobs)) == len(blobs)


def test_frontend_mapping_no_longer_uses_the_whole_sheet_or_borrowed_facades():
    with open(ASSET_MAPPING_TS, encoding="utf-8") as f:
        src = f.read()
    mapping = dict(re.findall(r"'([a-z-]+)': '([a-z_]+)',", src.split("DISTRICT_TO_BUILDING")[1].split("}")[0]))
    assert mapping["recovery-center"] == "recovery_center"
    assert mapping["journal-library"] == "journal_library"
    assert mapping["training-arena"] == "training_arena"
    assert "buildings_sheet" not in mapping.values()
