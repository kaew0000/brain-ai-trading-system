"""world/workspace/layout_manager.py — Phase W12, Feature 1.

Resizable/dockable/collapsible panel layout, persisted to
`world/data/runtime/workspace.json`. Deliberately separate from
`world/data/runtime/world.json` etc. (Phase W4's own five files) — this
is UI preference state, not a trading-engine snapshot, and
`RuntimeManager` never reads or writes it. No external dependency: plain
JSON read/write, matching every other persistence in `world/`.
"""

import json
import os

from world.workspace.models import PanelLayout, WorkspaceLayout

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
WORLD_ROOT = os.path.dirname(_THIS_DIR)
DEFAULT_WORKSPACE_PATH = os.path.join(WORLD_ROOT, "data", "runtime", "workspace.json")

DEFAULT_PANEL_IDS = (
    "ops-dashboard", "agent-ceo", "agent-risk", "agent-execution", "agent-market",
    "agent-regime", "agent-portfolio", "agent-learning", "notifications",
    "missions", "search", "history", "performance",
)


def default_layout() -> WorkspaceLayout:
    """A sane starting layout — a simple grid, all panels open,
    none collapsed. Never written to disk until `save_layout()` is
    explicitly called; `load_layout()` returns this in memory when no
    file exists yet, rather than creating one implicitly."""
    panels = tuple(
        PanelLayout(panel_id=pid, x=float((i % 4) * 300), y=float((i // 4) * 220), width=290.0, height=200.0)
        for i, pid in enumerate(DEFAULT_PANEL_IDS)
    )
    return WorkspaceLayout(panels=panels, open_panel_ids=DEFAULT_PANEL_IDS)


class LayoutManager:
    def __init__(self, path: str = DEFAULT_WORKSPACE_PATH) -> None:
        self._path = path

    def load(self) -> WorkspaceLayout:
        if not os.path.isfile(self._path):
            return default_layout()
        try:
            with open(self._path) as f:
                content = f.read().strip()
            if not content:
                return default_layout()
            return WorkspaceLayout.from_dict(json.loads(content))
        except (OSError, json.JSONDecodeError, KeyError):
            return default_layout()

    def save(self, layout: WorkspaceLayout) -> None:
        os.makedirs(os.path.dirname(self._path), exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(layout.to_dict(), f, indent=2)

    def resize_panel(self, layout: WorkspaceLayout, panel_id: str, width: float, height: float) -> WorkspaceLayout:
        return self._replace_panel(layout, panel_id, lambda p: PanelLayout(
            panel_id=p.panel_id, x=p.x, y=p.y, width=width, height=height,
            collapsed=p.collapsed, docked=p.docked, z_order=p.z_order,
        ))

    def move_panel(self, layout: WorkspaceLayout, panel_id: str, x: float, y: float) -> WorkspaceLayout:
        return self._replace_panel(layout, panel_id, lambda p: PanelLayout(
            panel_id=p.panel_id, x=x, y=y, width=p.width, height=p.height,
            collapsed=p.collapsed, docked=p.docked, z_order=p.z_order,
        ))

    def set_collapsed(self, layout: WorkspaceLayout, panel_id: str, collapsed: bool) -> WorkspaceLayout:
        return self._replace_panel(layout, panel_id, lambda p: PanelLayout(
            panel_id=p.panel_id, x=p.x, y=p.y, width=p.width, height=p.height,
            collapsed=collapsed, docked=p.docked, z_order=p.z_order,
        ))

    def set_docked(self, layout: WorkspaceLayout, panel_id: str, docked: bool) -> WorkspaceLayout:
        return self._replace_panel(layout, panel_id, lambda p: PanelLayout(
            panel_id=p.panel_id, x=p.x, y=p.y, width=p.width, height=p.height,
            collapsed=p.collapsed, docked=docked, z_order=p.z_order,
        ))

    def close_panel(self, layout: WorkspaceLayout, panel_id: str) -> WorkspaceLayout:
        return WorkspaceLayout(
            panels=layout.panels,
            open_panel_ids=tuple(pid for pid in layout.open_panel_ids if pid != panel_id),
            version=layout.version,
        )

    def restore_panel(self, layout: WorkspaceLayout, panel_id: str) -> WorkspaceLayout:
        if panel_id in layout.open_panel_ids:
            return layout
        return WorkspaceLayout(
            panels=layout.panels, open_panel_ids=(*layout.open_panel_ids, panel_id), version=layout.version,
        )

    def reset(self) -> WorkspaceLayout:
        return default_layout()

    @staticmethod
    def _replace_panel(layout: WorkspaceLayout, panel_id: str, build) -> WorkspaceLayout:
        panels = tuple(build(p) if p.panel_id == panel_id else p for p in layout.panels)
        return WorkspaceLayout(panels=panels, open_panel_ids=layout.open_panel_ids, version=layout.version)
