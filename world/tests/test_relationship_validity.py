"""Placeholder test: relationships reference known agents; districts reference known districts/agents."""
import json
import os

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CHAR_DIR = os.path.join(WORLD_ROOT, "characters", "definitions")
DISTRICT_DIR = os.path.join(WORLD_ROOT, "districts", "definitions")
SAMPLE_RELATIONSHIPS = os.path.join(WORLD_ROOT, "data", "samples", "relationships.sample.json")


def _known_agent_refs():
    refs = set()
    for fname in os.listdir(CHAR_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(CHAR_DIR, fname)) as f:
                refs.add(json.load(f)["agentRef"])
    return refs


def _known_district_ids():
    ids = set()
    for fname in os.listdir(DISTRICT_DIR):
        if fname.endswith(".json"):
            with open(os.path.join(DISTRICT_DIR, fname)) as f:
                ids.add(json.load(f)["id"])
    return ids


def test_relationship_sample_references_known_agents():
    refs = _known_agent_refs()
    with open(SAMPLE_RELATIONSHIPS) as f:
        rels = json.load(f)
    for r in rels:
        assert r["from"] in refs, f"Unknown agent in relationship 'from': {r['from']}"
        assert r["to"] in refs, f"Unknown agent in relationship 'to': {r['to']}"


def test_district_connections_reference_known_districts():
    ids = _known_district_ids()
    for fname in os.listdir(DISTRICT_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(DISTRICT_DIR, fname)) as f:
            d = json.load(f)
        for conn in d["connectedDistricts"]:
            assert conn in ids, f"{d['id']} references unknown connected district {conn}"


def test_district_assigned_agents_reference_known_agents():
    refs = _known_agent_refs()
    for fname in os.listdir(DISTRICT_DIR):
        if not fname.endswith(".json"):
            continue
        with open(os.path.join(DISTRICT_DIR, fname)) as f:
            d = json.load(f)
        for agent in d["assignedAgents"]:
            assert agent in refs, f"{d['id']} references unknown agent {agent}"
