"""Phase W2: navigation graph must be internally consistent — every edge
points at a real node, every room has a path to the building's Reception
(the entry point), and every floor's elevator is reachable. Path graph only,
no pathfinding algorithm and no renderer are implemented here."""
import json
import os
from collections import defaultdict, deque

WORLD_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _graph():
    with open(os.path.join(WORLD_ROOT, "data", "navigation", "graph.json")) as f:
        return json.load(f)


def _adjacency(graph):
    adj = defaultdict(set)
    for e in graph["edges"]:
        adj[e["from"]].add(e["to"])
        adj[e["to"]].add(e["from"])  # navigation is undirected (corridors go both ways)
    return adj


def test_every_edge_references_a_known_node():
    graph = _graph()
    node_ids = {n["id"] for n in graph["nodes"]}
    for e in graph["edges"]:
        assert e["from"] in node_ids, f"edge from unknown node {e['from']}"
        assert e["to"] in node_ids, f"edge to unknown node {e['to']}"


def test_node_ids_are_unique():
    graph = _graph()
    ids = [n["id"] for n in graph["nodes"]]
    assert len(ids) == len(set(ids))


def test_every_room_has_an_elevator_edge_on_its_floor():
    graph = _graph()
    rooms_by_floor = defaultdict(list)
    elevators_by_floor = {}
    for n in graph["nodes"]:
        if n["type"] == "room":
            rooms_by_floor[n["floor"]].append(n["id"])
        elif n["type"] == "elevator":
            elevators_by_floor[n["floor"]] = n["id"]

    adj = _adjacency(graph)
    for floor, room_ids in rooms_by_floor.items():
        elevator_id = elevators_by_floor[floor]
        for rid in room_ids:
            assert elevator_id in adj[rid], f"{rid} on floor {floor} has no edge to {elevator_id}"


def test_graph_is_fully_connected_from_reception():
    """Every node must be reachable from world-gateway (Reception) — no
    isolated room in the building."""
    graph = _graph()
    adj = _adjacency(graph)
    all_ids = {n["id"] for n in graph["nodes"]}

    visited = set()
    queue = deque(["world-gateway"])
    while queue:
        cur = queue.popleft()
        if cur in visited:
            continue
        visited.add(cur)
        queue.extend(adj[cur] - visited)

    assert visited == all_ids, f"unreachable nodes from Reception: {all_ids - visited}"
