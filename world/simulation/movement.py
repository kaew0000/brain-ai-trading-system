"""Movement system — Part D. Abstract, logical position only: no renderer
code, no pixels, no easing curves — just a `Position` that moves toward a
target by a fixed logical step size each tick.

`NavigationGraph` answers "what room-to-room path gets me there" using the
real `world/data/navigation/graph.json` (Phase W2) distances. `MovementPlan`
/ `MovementController` answer "where exactly is this agent right now,
mid-transition."
"""

import heapq
import json
import math
import os
from dataclasses import dataclass, field

from world.simulation.models import Position

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_THIS_DIR)
DEFAULT_GRAPH_PATH = os.path.join(WORLD_ROOT, "data", "navigation", "graph.json")

#: Logical units an agent covers per tick while walking. A design constant
#: (matches `SimulationClock.SECONDS_PER_TICK` = 1 logical second/tick),
#: not tied to any renderer's pixel scale. Deliberately smaller than the
#: typical spacing between spatial_placement.json patrol waypoints
#: (0.5-1.0 units) so walking spans multiple ticks instead of an
#: instantaneous single-tick "teleport" to the next waypoint.
STEP_DISTANCE_PER_TICK = 0.2
ARRIVAL_EPSILON = 1e-6


class NavigationGraph:
    """Loads `world/data/navigation/graph.json` once and answers shortest
    room-to-room paths via Dijkstra over the graph's own `distance`
    weights. Read-only; never modifies the graph file."""

    def __init__(self, graph_path: str = DEFAULT_GRAPH_PATH) -> None:
        self._adjacency: dict[str, list[tuple[str, float]]] = {}
        if os.path.isfile(graph_path):
            with open(graph_path) as f:
                graph = json.load(f)
            for node in graph.get("nodes", []):
                self._adjacency.setdefault(node["id"], [])
            for edge in graph.get("edges", []):
                dist = float(edge.get("distance", 1.0))
                self._adjacency.setdefault(edge["from"], []).append((edge["to"], dist))
                self._adjacency.setdefault(edge["to"], []).append((edge["from"], dist))

    def shortest_path(self, start: str, goal: str) -> list[str]:
        """Dijkstra shortest path as a list of room ids, `[start, ..., goal]`.
        Returns `[start]` if `start == goal`, or `[]` if unreachable/either
        room is unknown."""
        if start == goal:
            return [start] if start in self._adjacency else []
        if start not in self._adjacency or goal not in self._adjacency:
            return []

        distances = {start: 0.0}
        previous: dict[str, str] = {}
        visited = set()
        heap = [(0.0, start)]

        while heap:
            dist, node = heapq.heappop(heap)
            if node in visited:
                continue
            visited.add(node)
            if node == goal:
                break
            for neighbor, weight in self._adjacency.get(node, []):
                candidate = dist + weight
                if candidate < distances.get(neighbor, math.inf):
                    distances[neighbor] = candidate
                    previous[neighbor] = node
                    heapq.heappush(heap, (candidate, neighbor))

        if goal not in distances:
            return []

        path = [goal]
        while path[-1] != start:
            path.append(previous[path[-1]])
        path.reverse()
        return path


@dataclass
class MovementPlan:
    """One agent's in-progress movement: where it is, where it's headed,
    and any waypoints (room ids) still to pass through first."""

    current_position: Position
    current_room_id: str
    target_position: Position | None = None
    target_room_id: str | None = None
    room_waypoints: list[str] = field(default_factory=list)


def _step_toward(current: Position, target: Position, max_distance: float) -> tuple[Position, bool]:
    """Move `current` toward `target` by at most `max_distance`. Returns
    `(new_position, arrived)`."""
    dx, dy = target.x - current.x, target.y - current.y
    distance = math.hypot(dx, dy)
    if distance <= max(max_distance, ARRIVAL_EPSILON):
        return target, True
    ratio = max_distance / distance
    return Position(x=current.x + dx * ratio, y=current.y + dy * ratio), False


class MovementController:
    """Holds one `MovementPlan` per agent and advances them one logical
    step per call to `step()`. Room transitions (Part D) are just a
    special case of "target position is in a different room": the
    controller walks the agent to that room's designated entry position
    room-by-room using `NavigationGraph`, matching a patrol route or a
    meeting destination the same way."""

    def __init__(self, graph: NavigationGraph | None = None) -> None:
        self._graph = graph or NavigationGraph()
        self._plans: dict[str, MovementPlan] = {}

    def place(self, agent_id: str, position: Position, room_id: str) -> None:
        """Set an agent's position directly (e.g. on first tick / reset),
        with no pending destination."""
        self._plans[agent_id] = MovementPlan(current_position=position, current_room_id=room_id)

    def set_destination(self, agent_id: str, target_position: Position, target_room_id: str) -> None:
        plan = self._plans.get(agent_id)
        if plan is None:
            # Never seen before: place it at the target immediately rather
            # than crash — `place()` should normally run first.
            self.place(agent_id, target_position, target_room_id)
            return
        if plan.current_room_id == target_room_id:
            plan.target_position = target_position
            plan.target_room_id = target_room_id
            plan.room_waypoints = []
            return
        path = self._graph.shortest_path(plan.current_room_id, target_room_id)
        plan.target_position = target_position
        plan.target_room_id = target_room_id
        # path[0] is the current room; the rest are rooms still to enter.
        plan.room_waypoints = path[1:] if path else [target_room_id]

    def step(self, agent_id: str) -> Position:
        """Advance one agent by one tick toward its current destination
        (if any). Returns its (possibly unchanged) position."""
        plan = self._plans.get(agent_id)
        if plan is None or plan.target_position is None:
            return plan.current_position if plan else Position(0.0, 0.0)

        if plan.room_waypoints:
            next_room = plan.room_waypoints[0]
            # Walk toward the target position, entering the next room once
            # reached — a simplified model that still produces genuine
            # multi-tick, multi-room transitions for patrol routes and
            # meeting destinations alike.
            new_pos, arrived = _step_toward(
                plan.current_position, plan.target_position, STEP_DISTANCE_PER_TICK
            )
            plan.current_position = new_pos
            plan.current_room_id = next_room
            plan.room_waypoints = plan.room_waypoints[1:]
            if arrived and not plan.room_waypoints:
                plan.target_position = None
                plan.target_room_id = None
            return plan.current_position

        new_pos, arrived = _step_toward(
            plan.current_position, plan.target_position, STEP_DISTANCE_PER_TICK
        )
        plan.current_position = new_pos
        if arrived:
            plan.target_position = None
            plan.target_room_id = None
        return plan.current_position

    def has_arrived(self, agent_id: str) -> bool:
        plan = self._plans.get(agent_id)
        return plan is None or plan.target_position is None

    def current_room(self, agent_id: str) -> str | None:
        plan = self._plans.get(agent_id)
        return plan.current_room_id if plan else None

    def current_position(self, agent_id: str) -> Position | None:
        plan = self._plans.get(agent_id)
        return plan.current_position if plan else None
