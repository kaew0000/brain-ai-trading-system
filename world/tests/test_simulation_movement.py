"""Phase W7, Part D: movement system."""
import json

import pytest

from world.simulation.models import Position
from world.simulation.movement import MovementController, NavigationGraph


@pytest.fixture
def small_graph_path(tmp_path):
    graph = {
        "nodes": [{"id": "a", "type": "room"}, {"id": "b", "type": "room"},
                  {"id": "c", "type": "room"}, {"id": "isolated", "type": "room"}],
        "edges": [
            {"from": "a", "to": "b", "distance": 1.0},
            {"from": "b", "to": "c", "distance": 1.0},
            {"from": "a", "to": "c", "distance": 5.0},
        ],
    }
    path = tmp_path / "graph.json"
    path.write_text(json.dumps(graph))
    return str(path)


def test_shortest_path_same_room(small_graph_path):
    graph = NavigationGraph(small_graph_path)
    assert graph.shortest_path("a", "a") == ["a"]


def test_shortest_path_prefers_lower_total_distance(small_graph_path):
    graph = NavigationGraph(small_graph_path)
    assert graph.shortest_path("a", "c") == ["a", "b", "c"]


def test_shortest_path_unreachable_room_returns_empty(small_graph_path):
    graph = NavigationGraph(small_graph_path)
    assert graph.shortest_path("a", "isolated") == []


def test_shortest_path_unknown_room_returns_empty(small_graph_path):
    graph = NavigationGraph(small_graph_path)
    assert graph.shortest_path("a", "not-a-real-room") == []


def test_real_navigation_graph_connects_all_departments():
    """Sanity check against the actual Phase W2 graph shipped in this
    repo: every *department* (the graph's real node set) should reach
    every other department.

    Note: `lobby` / `hallway` (generic `CirculationType` ids used to
    populate `world/data/assets/room_assets.json` in the Phase W6 asset
    pipeline) are NOT nodes in this graph at all — only the 14 departments
    plus `elevator-floor-1/2/3` are. No real character's home room is
    `lobby`/`hallway` (see `world/data/characters/placement.json`), so this
    doesn't affect movement for any of the 16 real characters, but it's a
    real naming mismatch between Phase W2 (navigation graph) and Phase W6
    (asset/room population) worth flagging rather than silently masking."""
    graph = NavigationGraph()  # default path = real world/data/navigation/graph.json
    assert graph.shortest_path("ceo-tower", "world-gateway") != []
    assert graph.shortest_path("risk-fortress", "data-center") != []


def test_movement_controller_place_sets_position_with_no_pending_target():
    controller = MovementController()
    controller.place("primus", Position(1.0, 1.0), "ceo-tower")
    assert controller.has_arrived("primus") is True
    assert controller.current_position("primus") == Position(1.0, 1.0)
    assert controller.current_room("primus") == "ceo-tower"


def test_movement_controller_steps_toward_target_within_same_room():
    controller = MovementController()
    controller.place("primus", Position(0.0, 0.0), "ceo-tower")
    controller.set_destination("primus", Position(1.0, 0.0), "ceo-tower")
    assert controller.has_arrived("primus") is False

    positions = [controller.step("primus") for _ in range(20)]
    assert controller.has_arrived("primus") is True
    assert positions[-1] == Position(1.0, 0.0)


def test_movement_controller_never_overshoots_target():
    controller = MovementController()
    controller.place("primus", Position(0.0, 0.0), "ceo-tower")
    controller.set_destination("primus", Position(0.05, 0.0), "ceo-tower")
    pos = controller.step("primus")
    assert pos.x == pytest.approx(0.05)
    assert controller.has_arrived("primus") is True


def test_movement_controller_room_transition_uses_real_graph(small_graph_path):
    graph = NavigationGraph(small_graph_path)
    controller = MovementController(graph=graph)
    controller.place("primus", Position(0.0, 0.0), "a")
    controller.set_destination("primus", Position(5.0, 0.0), "c")

    for _ in range(200):
        controller.step("primus")
        if controller.has_arrived("primus"):
            break

    assert controller.has_arrived("primus") is True
    assert controller.current_room("primus") == "c"


def test_unknown_agent_step_returns_origin_without_crashing():
    controller = MovementController()
    assert controller.step("ghost") == Position(0.0, 0.0)
    assert controller.has_arrived("ghost") is True
