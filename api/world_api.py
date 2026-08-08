"""
api/world_api.py — Phase W10: Live Command Center UI (backend layer)

REST read layer over world.runtime, world.simulation, world.interaction,
and world.frontend.renderer — the four Track B public APIs Phases
W5/W7/W9/W8 already built. Additive: an APIRouter included into the
existing api/app.py singleton (same pattern every other /api/* route in
this codebase already uses — see api/portfolio_api.py), not a second
FastAPI app.

Every function this module calls is one of world.*.api's already-public,
already-tested entry points. Nothing here imports agents/, execution/,
portfolio/, risk/, journal/, decision/, or main.py — Track A stays
completely untouched, matching every prior World phase's hard constraint.
The only two calls with any side effect at all are timeline
play/pause/resume/seek and simulation pause/resume (via
world.interaction.api.dispatch), both already documented in
world/interaction/api.py as affecting only the *visualization*, never the
trading engine.

Auth: routes are under /api/world/*, so the existing _auth_middleware in
api/app.py already covers them at the default VIEWER role — nothing in
api/auth.py needed changing (same note api/portfolio_api.py makes).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import JSONResponse

from world.frontend.renderer import api as renderer_api
from world.interaction import api as interaction_api
from world.runtime import api as runtime_api
from world.simulation import api as simulation_api

router = APIRouter(prefix="/api/world", tags=["world"])


def _ok(data) -> JSONResponse:
    # Mirrors api/app.py's own _ok() envelope shape exactly, same reason
    # api/portfolio_api.py's copy gives: avoids a circular import back
    # into api.app (which is the one that includes this router).
    return JSONResponse(content={"ok": True, "data": data})


# ── Backend state (Phase W5 + W7) ───────────────────────────────────────

@router.get("/state")
async def get_world_state():
    return _ok(runtime_api.get_world_state().to_dict())


@router.get("/simulation")
async def get_simulation_state():
    return _ok(simulation_api.get_simulation_state().to_dict())


@router.get("/rooms")
async def list_rooms():
    state = simulation_api.get_simulation_state()
    return _ok([r.to_dict() for r in state.rooms])


@router.get("/rooms/{room_id}")
async def get_room(room_id: str):
    room = simulation_api.get_room_activity(room_id)
    if room is None:
        raise HTTPException(status_code=404, detail=f"Unknown room: {room_id!r}")
    return _ok(room.to_dict())


@router.get("/characters/{agent_id}")
async def get_character(agent_id: str):
    character = simulation_api.get_character_activity(agent_id)
    if character is None:
        raise HTTPException(status_code=404, detail=f"Unknown character: {agent_id!r}")
    return _ok(character.to_dict())


@router.get("/events")
async def get_events():
    return _ok([e.to_dict() for e in simulation_api.get_current_events()])


# ── Rendering (Phase W8) ─────────────────────────────────────────────────

@router.get("/rooms/{room_id}/frame")
async def get_room_frame(room_id: str):
    if room_id not in renderer_api.known_room_ids():
        raise HTTPException(status_code=404, detail=f"Unknown room: {room_id!r}")
    frame = renderer_api.get_render_frame(room_id)
    return _ok(frame.to_dict())


# ── Interaction (Phase W9): selection, hover, inspector, search ─────────

@router.post("/select/{kind}/{target_id}")
async def select(kind: str, target_id: str):
    try:
        result = interaction_api.select(kind, target_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(result.to_dict())


@router.get("/selection")
async def current_selection():
    selection = interaction_api.current_selection()
    return _ok(selection.to_dict() if selection else None)


@router.post("/hover/{kind}/{target_id}")
async def hover(kind: str, target_id: str):
    try:
        result = interaction_api.hover(kind, target_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(result.to_dict())


@router.get("/inspect/{kind}/{target_id}")
async def inspect(kind: str, target_id: str):
    try:
        report = interaction_api.inspect(kind, target_id)
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _ok(report.to_dict())


@router.get("/search")
async def search(q: str = Query(..., min_length=1)):
    return _ok([r.to_dict() for r in interaction_api.search_world(q)])


@router.get("/notifications")
async def notifications(category: str | None = Query(default=None)):
    if category:
        results = interaction_api.get_notifications_by_category(category)
    else:
        results = interaction_api.get_notifications()
    return _ok([n.to_dict() for n in results])


# ── Timeline (Phase W7 + W9) ────────────────────────────────────────────
# Basic playback (play/pause/resume/seek) goes straight to
# `simulation_api.get_timeline()` — the real Phase W9 addition to
# world.simulation.api — since these aren't part of
# world.interaction.command_dispatcher's 9-command
# `READ_ONLY_COMMANDS` set. `jump_to_event` and `show_timeline` ARE in
# that set (they need CommandDispatcher's event-publishing/history-
# recording side effects), so those two go through `interaction_api.
# dispatch` instead. Either path only ever moves the *view* cursor —
# never the trading engine, never `world.runtime`.

@router.get("/timeline")
async def get_timeline():
    timeline = simulation_api.get_timeline()
    current = timeline.current()
    return _ok({
        "length": len(timeline),
        "isPlaying": timeline.is_playing(),
        "current": current.to_dict() if current else None,
    })


@router.post("/timeline/play")
async def timeline_play():
    simulation_api.get_timeline().play()
    return _ok({"isPlaying": True})


@router.post("/timeline/pause")
async def timeline_pause():
    simulation_api.get_timeline().pause()
    return _ok({"isPlaying": False})


@router.post("/timeline/resume")
async def timeline_resume():
    simulation_api.get_timeline().resume()
    return _ok({"isPlaying": True})


@router.post("/timeline/seek")
async def timeline_seek(tick: int = Query(...)):
    state = simulation_api.get_timeline().seek(tick)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Tick {tick} is not in retained history")
    return _ok(state.to_dict())


@router.post("/timeline/jump-to-event")
async def timeline_jump_to_event(event_id: str = Query(...)):
    result = interaction_api.dispatch("jump_to_event", actor="dashboard", event_id=event_id)
    if not result.ok:
        raise HTTPException(status_code=404, detail=result.detail)
    return _ok(result.to_dict())


# ── Camera + simulation controls (Phase W8/W9, view-only) ───────────────
# All nine real world.interaction.command_dispatcher.READ_ONLY_COMMANDS
# are reachable here; none of them can affect Track A.

_COMMAND_KWARG_NAMES = {
    "focus_room": "room_id",
    "follow_character": "character_id",
    "center_camera": "room_id",
    "highlight_department": "room_id",
    "set_simulation_speed": "speed",
}


@router.post("/command/{command}")
async def dispatch_command(command: str, target: str = Query(default=""), speed: float | None = Query(default=None)):
    kwargs = {}
    kwarg_name = _COMMAND_KWARG_NAMES.get(command)
    if kwarg_name == "speed":
        if speed is None:
            raise HTTPException(status_code=400, detail="speed is required for set_simulation_speed")
        kwargs["speed"] = speed
    elif kwarg_name is not None:
        if not target:
            raise HTTPException(status_code=400, detail=f"target is required for {command!r}")
        kwargs[kwarg_name] = target

    result = interaction_api.dispatch(command, actor="dashboard", **kwargs)
    if not result.ok:
        raise HTTPException(status_code=400, detail=result.detail or f"command {command!r} failed")
    return _ok(result.to_dict())
