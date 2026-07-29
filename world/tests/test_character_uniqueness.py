"""Placeholder test: character ids and agentRefs are unique."""
import json
import os

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")


def _load_all():
    items = []
    for fname in sorted(os.listdir(CHAR_DIR)):
        if fname.endswith(".json"):
            with open(os.path.join(CHAR_DIR, fname)) as f:
                items.append(json.load(f))
    return items


def test_character_ids_unique():
    items = _load_all()
    ids = [c["id"] for c in items]
    assert len(ids) == len(set(ids)), "Duplicate character ids found"


def test_character_agent_refs_unique():
    items = _load_all()
    refs = [c["agentRef"] for c in items]
    assert len(refs) == len(set(refs)), "Duplicate agentRef values found"
