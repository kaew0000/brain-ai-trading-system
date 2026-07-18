"""
graph/agent_graph.py
======================
Agent Relationship Graph (v14 Phase 2.5)

Builds a dependency tree of the agent layer in a shape ready for direct
consumption by React Flow (https://reactflow.dev) on the future Agent
Floor dashboard page — no client-side layout math required, though the
frontend remains free to override positions.

Topology
--------
CEO_AGENT is the hub; the 6 employee agents are spokes feeding into it.
Edge weight comes from CEOAgent.WEIGHTS (the actual aggregation weights
used in CEODecision scoring) — this is the single source of truth, so
the graph can never drift out of sync with real CEO behaviour.

TRADER is intentionally unweighted (weight=0.0) in CEO.WEIGHTS — it
feeds CEO context for execution-awareness only, not the weighted score.
This is reflected accurately rather than papered over.

Output shape
------------
{
  "nodes": [
    {"id": "ceo", "type": "agent",
     "data": {"label": "CEO Agent", "agent_name": "CEO_AGENT", "role": "Orchestrator"},
     "position": {"x": ..., "y": ...}},
    ...
  ],
  "edges": [
    {"id": "smc-ceo", "source": "smc", "target": "ceo",
     "data": {"weight": 0.30, "label": "30%"}},
    ...
  ]
}

Usage
-----
from graph.agent_graph import build_agent_graph

graph = build_agent_graph(agent_layer)   # agent_layer from _state, or None
graph = build_agent_graph(None)          # falls back to static topology
"""

from __future__ import annotations

import math
from typing import Dict, Optional

# Static fallback topology — used when the live agent_layer isn't available
# yet (e.g. dashboard loaded before the bot has finished booting). Keys and
# roles mirror agents/__init__.py build_agent_layer() exactly.
_STATIC_AGENTS = {
    "smc":     {"name": "SMC_ANALYST",     "label": "SMC Analyst",     "role": "Smart Money Concepts"},
    "futures": {"name": "FUTURES_ANALYST", "label": "Futures Analyst", "role": "OI & Funding"},
    "regime":  {"name": "REGIME_ANALYST",  "label": "Regime Analyst",  "role": "Market Regime"},
    "risk":    {"name": "RISK_MANAGER",    "label": "Risk Manager",    "role": "Risk Control"},
    "trader":  {"name": "TRADER",          "label": "Trader",          "role": "Execution Context"},
    "journal": {"name": "JOURNAL_ANALYST", "label": "Journal Analyst", "role": "Historical Performance"},
}

_STATIC_WEIGHTS = {
    "smc":     0.30,
    "futures": 0.25,
    "regime":  0.20,
    "risk":    0.15,
    "journal": 0.10,
    # "trader" deliberately absent — matches CEOAgent.WEIGHTS exactly
}

_CEO_NODE_ID = "ceo"
_HUB_RADIUS  = 280   # px — spoke distance from CEO in the default layout


def build_agent_graph(agent_layer: Optional[dict] = None) -> dict:
    """
    Build the agent dependency graph in React Flow node/edge format.

    Parameters
    ----------
    agent_layer : dict from agents.build_agent_layer(), or the live
                  _state["agent_layer"] from api.app. If None or missing
                  the "ceo" key, falls back to the static topology so the
                  endpoint always returns a valid, non-empty graph (the
                  dashboard should never see an empty canvas).

    Returns
    -------
    {"nodes": [...], "edges": [...], "weights_sum": float, "source": "live"|"static"}
    """
    if agent_layer and "ceo" in agent_layer:
        return _build_from_live_layer(agent_layer)
    return _build_static()


def _build_from_live_layer(agent_layer: dict) -> dict:
    ceo = agent_layer["ceo"]
    weights: Dict[str, float] = dict(getattr(ceo, "WEIGHTS", _STATIC_WEIGHTS))

    spoke_keys = [k for k in agent_layer.keys() if k != "ceo"]
    # Stable ordering: weighted agents first (by weight desc), then unweighted
    spoke_keys.sort(key=lambda k: (-weights.get(k, 0.0), k))

    nodes = [_ceo_node(getattr(ceo, "AGENT_NAME", "CEO_AGENT"))]
    edges = []

    n = max(len(spoke_keys), 1)
    for i, key in enumerate(spoke_keys):
        agent = agent_layer[key]
        agent_name = getattr(agent, "AGENT_NAME", key.upper())
        role = _infer_role(key)
        weight = round(float(weights.get(key, 0.0)), 4)

        x, y = _spoke_position(i, n)
        nodes.append({
            "id": key,
            "type": "agent",
            "data": {
                "label":      _infer_label(key),
                "agent_name": agent_name,
                "role":       role,
                "weighted":   key in weights,
            },
            "position": {"x": x, "y": y},
        })
        edges.append(_edge(key, weight))

    return {
        "nodes":       nodes,
        "edges":       edges,
        "weights_sum": round(sum(weights.values()), 4),
        "source":      "live",
    }


def _build_static() -> dict:
    nodes = [_ceo_node("CEO_AGENT")]
    edges = []

    spoke_keys = sorted(_STATIC_AGENTS.keys(),
                         key=lambda k: (-_STATIC_WEIGHTS.get(k, 0.0), k))
    n = len(spoke_keys)

    for i, key in enumerate(spoke_keys):
        meta = _STATIC_AGENTS[key]
        weight = round(_STATIC_WEIGHTS.get(key, 0.0), 4)
        x, y = _spoke_position(i, n)
        nodes.append({
            "id": key,
            "type": "agent",
            "data": {
                "label":      meta["label"],
                "agent_name": meta["name"],
                "role":       meta["role"],
                "weighted":   key in _STATIC_WEIGHTS,
            },
            "position": {"x": x, "y": y},
        })
        edges.append(_edge(key, weight))

    return {
        "nodes":       nodes,
        "edges":       edges,
        "weights_sum": round(sum(_STATIC_WEIGHTS.values()), 4),
        "source":      "static",
    }


def _ceo_node(agent_name: str) -> dict:
    return {
        "id": _CEO_NODE_ID,
        "type": "ceo",
        "data": {
            "label":      "CEO Agent",
            "agent_name": agent_name,
            "role":       "Orchestrator",
            "weighted":   None,
        },
        "position": {"x": 0, "y": 0},
    }


def _edge(source_key: str, weight: float) -> dict:
    return {
        "id":     f"{source_key}-{_CEO_NODE_ID}",
        "source": source_key,
        "target": _CEO_NODE_ID,
        "data": {
            "weight": weight,
            "label":  f"{weight * 100:.0f}%" if weight > 0 else "context only",
        },
    }


def _spoke_position(index: int, total: int) -> tuple[float, float]:
    """Even radial distribution around the CEO hub node."""
    angle = (2 * math.pi * index) / max(total, 1)
    x = round(_HUB_RADIUS * math.cos(angle), 1)
    y = round(_HUB_RADIUS * math.sin(angle), 1)
    return x, y


def _infer_label(key: str) -> str:
    return _STATIC_AGENTS.get(key, {}).get("label", key.replace("_", " ").title())


def _infer_role(key: str) -> str:
    return _STATIC_AGENTS.get(key, {}).get("role", "")
