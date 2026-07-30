"""NavigationRenderer — abstraction only. Draws the path graph from
`world/data/navigation/graph.json` (nodes + edges) — e.g. for a
minimap or a debug overlay. No pathfinding algorithm and no drawing
implementation live here; see `world/ui/specs/minimap.md` for the
panel this feeds."""

from abc import ABC, abstractmethod
from typing import Any


class NavigationRenderer(ABC):
    """Contract for drawing the navigation graph."""

    @abstractmethod
    def render_graph(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        """Render the full node/edge graph, e.g. as a minimap. Inputs
        are the parsed contents of
        `world/data/navigation/graph.json`."""
        raise NotImplementedError

    @abstractmethod
    def highlight_path(self, node_ids: list[str]) -> None:
        """Highlight an ordered sequence of already-known node ids
        (e.g. a route a character is walking). Computing that
        sequence is outside this interface's scope."""
        raise NotImplementedError
