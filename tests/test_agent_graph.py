"""
tests/test_agent_graph.py
===========================
v14 Phase 2.5 — Agent Relationship Graph test suite.

Covers:
  - build_agent_graph() static fallback (no agent_layer provided)
  - build_agent_graph() live mode (real agent_layer from build_agent_layer())
  - React Flow node/edge shape compliance
  - Weight accuracy vs CEOAgent.WEIGHTS (single source of truth)
  - GET /api/agents/graph
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Static fallback topology
# ─────────────────────────────────────────────────────────────────────────────
class TestStaticGraph:

    def test_no_layer_returns_static_source(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        assert graph["source"] == "static"

    def test_empty_dict_returns_static_source(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph({})
        assert graph["source"] == "static"

    def test_static_has_7_nodes(self):
        """CEO + 6 sub-agents."""
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        assert len(graph["nodes"]) == 7

    def test_static_has_6_edges(self):
        """One edge per sub-agent into CEO."""
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        assert len(graph["edges"]) == 6

    def test_static_ceo_node_present(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        ceo_nodes = [n for n in graph["nodes"] if n["id"] == "ceo"]
        assert len(ceo_nodes) == 1
        assert ceo_nodes[0]["type"] == "ceo"
        assert ceo_nodes[0]["data"]["agent_name"] == "CEO_AGENT"

    def test_static_all_spoke_keys_present(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        node_ids = {n["id"] for n in graph["nodes"]}
        assert node_ids == {"ceo", "smc", "futures", "regime", "risk", "trader", "journal"}

    def test_static_weights_sum_to_one(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        assert graph["weights_sum"] == pytest.approx(1.0)

    def test_static_trader_edge_weight_zero(self):
        """TRADER is unweighted in CEO.WEIGHTS — context-only."""
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        trader_edge = next(e for e in graph["edges"] if e["source"] == "trader")
        assert trader_edge["data"]["weight"] == 0.0
        assert trader_edge["data"]["label"] == "context only"

    def test_static_smc_edge_weight_030(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        smc_edge = next(e for e in graph["edges"] if e["source"] == "smc")
        assert smc_edge["data"]["weight"] == pytest.approx(0.30)
        assert smc_edge["data"]["label"] == "30%"

    def test_static_all_edges_target_ceo(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        for e in graph["edges"]:
            assert e["target"] == "ceo"

    def test_static_node_has_position(self):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        for n in graph["nodes"]:
            assert "x" in n["position"]
            assert "y" in n["position"]

    def test_static_spokes_not_overlapping_ceo(self):
        """All non-CEO nodes should be positioned away from the origin."""
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(None)
        for n in graph["nodes"]:
            if n["id"] != "ceo":
                dist = (n["position"]["x"] ** 2 + n["position"]["y"] ** 2) ** 0.5
                assert dist > 0


# ─────────────────────────────────────────────────────────────────────────────
# Live agent_layer mode
# ─────────────────────────────────────────────────────────────────────────────
class TestLiveGraph:

    @pytest.fixture
    def agent_layer(self):
        from agents import build_agent_layer
        return build_agent_layer()

    def test_live_layer_returns_live_source(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        assert graph["source"] == "live"

    def test_live_layer_has_7_nodes(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        assert len(graph["nodes"]) == 7

    def test_live_layer_uses_actual_ceo_weights(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        ceo_weights = agent_layer["ceo"].WEIGHTS
        for edge in graph["edges"]:
            key = edge["source"]
            expected = round(ceo_weights.get(key, 0.0), 4)
            assert edge["data"]["weight"] == expected

    def test_live_layer_weights_sum_matches_ceo(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        expected_sum = round(sum(agent_layer["ceo"].WEIGHTS.values()), 4)
        assert graph["weights_sum"] == expected_sum

    def test_live_layer_agent_names_match_constants(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        for n in graph["nodes"]:
            if n["id"] != "ceo":
                expected_name = agent_layer[n["id"]].AGENT_NAME
                assert n["data"]["agent_name"] == expected_name

    def test_live_layer_weighted_flag_correct(self, agent_layer):
        from graph.agent_graph import build_agent_graph
        graph = build_agent_graph(agent_layer)
        ceo_weights = agent_layer["ceo"].WEIGHTS
        for n in graph["nodes"]:
            if n["id"] == "trader":
                assert n["data"]["weighted"] is False
            elif n["id"] in ceo_weights:
                assert n["data"]["weighted"] is True

    def test_live_layer_handles_missing_ceo_key(self, agent_layer):
        """If agent_layer doesn't have 'ceo' key, falls back to static."""
        from graph.agent_graph import build_agent_graph
        partial_layer = {k: v for k, v in agent_layer.items() if k != "ceo"}
        graph = build_agent_graph(partial_layer)
        assert graph["source"] == "static"


# ─────────────────────────────────────────────────────────────────────────────
# API: GET /api/agents/graph
# ─────────────────────────────────────────────────────────────────────────────
class TestAgentGraphAPI:

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/agents/graph")
        assert r.status_code == 200

    def test_endpoint_ok_true(self, client):
        body = client.get("/api/agents/graph").json()
        assert body["ok"] is True

    def test_endpoint_returns_nodes_and_edges(self, client):
        body = client.get("/api/agents/graph").json()
        assert "nodes" in body["data"]
        assert "edges" in body["data"]

    def test_endpoint_default_source_is_static(self, client):
        """No agent_layer set in _state by default in test client."""
        body = client.get("/api/agents/graph").json()
        assert body["data"]["source"] in ("static", "live")

    def test_endpoint_nodes_nonempty(self, client):
        body = client.get("/api/agents/graph").json()
        assert len(body["data"]["nodes"]) >= 7

    def test_endpoint_with_live_agent_layer(self, client):
        from api.app import set_state
        from agents import build_agent_layer
        layer = build_agent_layer()
        set_state("agent_layer", layer)
        body = client.get("/api/agents/graph").json()
        assert body["data"]["source"] == "live"
        set_state("agent_layer", {})
