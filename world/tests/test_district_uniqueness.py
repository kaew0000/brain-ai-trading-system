"""Placeholder test: district ids and names are unique."""
import json
import os

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DISTRICT_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")


def _load_all():
    items = []
    for fname in sorted(os.listdir(DISTRICT_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(DISTRICT_DIR, fname)) as f:
                items.append(json.load(f))
    return items


def test_district_ids_unique():
    items = _load_all()
    ids = [d["id"] for d in items]
    assert len(ids) == len(set(ids)), "Duplicate district ids found"


def test_district_names_unique():
    items = _load_all()
    names = [d["name"] for d in items]
    assert len(names) == len(set(names)), "Duplicate district names found"
