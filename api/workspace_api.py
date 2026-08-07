"""
api/workspace_api.py — Phase W12: Live Operations Workspace & Command
Console (backend layer)

REST layer over `world.workspace.api` (Feature 10's own public facade),
which itself only reads `world.runtime`/`world.simulation`/
`world.interaction` — same additive-router pattern as `api/world_api.py`
(Phase W10), included into the same existing FastAPI singleton, not a
second app. Nothing here imports agents/, execution/, portfolio/, risk/,
journal/, learning/, strategy/, or exchange/ — Track A stays untouched.

Auth: routes are under /api/workspace/*, so the existing
_auth_middleware in api/app.py already covers them at the default
VIEWER role — nothing in api/auth.py needed changing (same note
api/world_api.py and api/portfolio_api.py make).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from world.workspace import api as workspace_api
from world.workspace.models import WorkspaceLayout

router = APIRouter(prefix="/api/workspace", tags=["workspace"])


def _ok(data) -> JSONResponse:
    return JSONResponse(content={"ok": True, "data": data})


# ── Feature 1: layout ────────────────────────────────────────────────────

@router.get("/layout")
async def get_layout():
    return _ok(workspace_api.get_layout().to_dict())


@router.post("/layout")
async def save_layout(layout: dict):
    workspace_api.save_layout(WorkspaceLayout.from_dict(layout))
    return _ok(workspace_api.get_layout().to_dict())


@router.post("/layout/panels/{panel_id}/resize")
async def resize_panel(panel_id: str, width: float = Query(...), height: float = Query(...)):
    return _ok(workspace_api.resize_panel(panel_id, width, height).to_dict())


@router.post("/layout/panels/{panel_id}/move")
async def move_panel(panel_id: str, x: float = Query(...), y: float = Query(...)):
    return _ok(workspace_api.move_panel(panel_id, x, y).to_dict())


@router.post("/layout/panels/{panel_id}/collapse")
async def collapse_panel(panel_id: str, collapsed: bool = Query(...)):
    return _ok(workspace_api.set_panel_collapsed(panel_id, collapsed).to_dict())


@router.post("/layout/panels/{panel_id}/close")
async def close_panel(panel_id: str):
    return _ok(workspace_api.close_panel(panel_id).to_dict())


@router.post("/layout/panels/{panel_id}/restore")
async def restore_panel(panel_id: str):
    return _ok(workspace_api.restore_panel(panel_id).to_dict())


@router.post("/layout/reset")
async def reset_layout():
    return _ok(workspace_api.reset_layout().to_dict())


# ── Feature 2: agent panels ──────────────────────────────────────────────

@router.get("/agents")
async def get_agent_panels():
    return _ok([p.to_dict() for p in workspace_api.get_agent_panels()])


# ── Feature 3: operations dashboard ──────────────────────────────────────

@router.get("/operations")
async def get_operations_summary():
    return _ok(workspace_api.get_operations_summary().to_dict())


# ── Feature 4: notification dock ─────────────────────────────────────────

@router.get("/notifications")
async def get_notification_dock(category: str | None = Query(default=None), unread_only: bool = Query(default=False)):
    return _ok([n.to_dict() for n in workspace_api.get_notification_dock(category=category, unread_only=unread_only)])


@router.post("/notifications/{notification_id}/pin")
async def pin_notification(notification_id: str):
    workspace_api.pin_notification(notification_id)
    return _ok({"id": notification_id, "pinned": True})


@router.post("/notifications/{notification_id}/unpin")
async def unpin_notification(notification_id: str):
    workspace_api.unpin_notification(notification_id)
    return _ok({"id": notification_id, "pinned": False})


@router.post("/notifications/{notification_id}/clear")
async def clear_notification(notification_id: str):
    workspace_api.clear_notification(notification_id)
    return _ok({"id": notification_id, "cleared": True})


@router.post("/notifications/clear-all")
async def clear_all_notifications():
    workspace_api.clear_all_notifications()
    return _ok({"cleared": True})


# ── Feature 5: mission workspace ─────────────────────────────────────────

@router.get("/missions")
async def get_mission_workspace():
    grouped = workspace_api.get_mission_workspace()
    return _ok({bucket: [item.to_dict() for item in items] for bucket, items in grouped.items()})


# ── Feature 6: search ──────────────────────────────────────────────────────

@router.get("/search")
async def search(q: str = Query(..., min_length=1), kinds: str | None = Query(default=None)):
    kind_tuple = tuple(kinds.split(",")) if kinds else None
    return _ok([r.to_dict() for r in workspace_api.search(q, kinds=kind_tuple)])


# ── Feature 7: quick navigation ──────────────────────────────────────────

@router.get("/quick-nav")
async def quick_nav(q: str = Query(..., min_length=1)):
    return _ok([r.to_dict() for r in workspace_api.quick_nav(q)])


# ── Feature 8: history ────────────────────────────────────────────────────

@router.post("/history")
async def record_history(kind: str = Query(...), payload: dict | None = None):
    return _ok(workspace_api.record_history(kind, payload or {}))


@router.post("/history/undo")
async def undo_navigation():
    entry = workspace_api.undo_navigation()
    if entry is None:
        raise HTTPException(status_code=404, detail="No earlier history entry to undo to")
    return _ok(entry)


@router.get("/history")
async def get_history():
    return _ok(list(workspace_api.get_history()))


# ── Feature 9: performance overlay ───────────────────────────────────────

@router.get("/performance")
async def get_performance_overlay():
    return _ok(workspace_api.get_performance_overlay().to_dict())
