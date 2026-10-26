"""
api/world_chat_api.py — V16 §83: World chat & meetings (REST layer).

Additive router over `world.chat.api`. Same /api/world/* prefix, so the
existing prefix-generic _auth_middleware already enforces auth (VIEWER) —
no api/auth.py change. Nothing here imports agents/, execution/,
portfolio/, risk/, journal/, learning/, strategy/ or exchange/.

Auto-mode meetings are paced by ONE asyncio task (`_driver`), created on
start/resume and cancelled on pause/stop/finish and at app shutdown, so
there is never more than one driver and nothing outlives the meeting.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from config.settings import settings
from utils.logger import get_logger
from world.chat import api as chat_api
from world.chat.meeting import MeetingError
from world.chat.models import MODE_AUTO, MODE_MANUAL, STATUS_RUNNING

logger = get_logger("api.world_chat")

router = APIRouter(prefix="/api/world/chat", tags=["world-chat"])

_driver_task: asyncio.Task | None = None


def _ok(data) -> JSONResponse:
    return JSONResponse(content={"ok": True, "data": data})


def _require_enabled() -> None:
    if not settings.WORLD_CHAT_ENABLED:
        raise HTTPException(status_code=503, detail="world chat disabled (WORLD_CHAT_ENABLED=false)")


def _bad(exc: Exception, status: int = 400) -> HTTPException:
    return HTTPException(status_code=status, detail=str(exc))


async def _drive() -> None:
    """Advance an auto meeting one turn per interval until it stops being
    `running` (paused/stopped/finished) or auto mode is not in effect."""
    try:
        while True:
            m = chat_api.get_meeting()
            if m.status != STATUS_RUNNING or m.mode != MODE_AUTO:
                return
            await asyncio.sleep(settings.WORLD_MEETING_TURN_INTERVAL_SECONDS)
            m = chat_api.get_meeting()
            if m.status != STATUS_RUNNING or m.mode != MODE_AUTO:
                return
            chat_api.meeting_next()
    except asyncio.CancelledError:
        raise
    except Exception:  # noqa: BLE001 — recovery: never leave a meeting "running" with a dead driver
        logger.exception("world.chat: meeting driver crashed; stopping meeting")
        try:
            chat_api.meeting_stop()
        except MeetingError:
            pass


def _cancel_driver() -> None:
    global _driver_task
    if _driver_task is not None and not _driver_task.done():
        _driver_task.cancel()
    _driver_task = None


def _ensure_driver() -> None:
    global _driver_task
    _cancel_driver()
    m = chat_api.get_meeting()
    if m.status == STATUS_RUNNING and m.mode == MODE_AUTO:
        _driver_task = asyncio.get_running_loop().create_task(_drive(), name="world-meeting-driver")


async def shutdown_driver() -> None:
    """Called from app shutdown so no task outlives the event loop."""
    _cancel_driver()


class PostMessage(BaseModel):
    channel: str = Field(default="office", max_length=80)
    text: str = Field(max_length=10_000)  # real cap is settings.WORLD_CHAT_MAX_TEXT_CHARS


class StartMeeting(BaseModel):
    topic: str = Field(max_length=500)
    participants: list[str] = Field(max_length=64)
    maxTurns: int | None = None
    mode: str = MODE_AUTO
    hybrid: bool = False


@router.get("/roster")
async def roster():
    _require_enabled()
    return _ok({"engine": "rule-based", "agents": chat_api.get_roster()})


@router.get("/messages")
async def messages(channel: str = Query(default="office"), limit: int = Query(default=100, ge=1),
                   after: str | None = Query(default=None)):
    _require_enabled()
    try:
        return _ok(chat_api.list_messages(channel, limit, after))
    except chat_api.ChatError as exc:
        raise _bad(exc)


@router.post("/messages")
async def post_message(body: PostMessage, request: Request):
    _require_enabled()
    auth = getattr(request.state, "auth", None)
    sender_id = getattr(auth, "principal", None) or "operator"
    try:
        result = chat_api.post_message(body.channel, body.text, str(sender_id), "You")
    except chat_api.ChatError as exc:
        raise _bad(exc)
    if body.channel == "meeting":
        _ensure_driver()  # a hybrid interjection pauses -> driver must stop
    return _ok(result)


@router.get("/meeting")
async def get_meeting():
    _require_enabled()
    return _ok(chat_api.get_meeting().to_dict())


@router.post("/meeting/start")
async def start_meeting(body: StartMeeting):
    _require_enabled()
    if body.mode not in (MODE_AUTO, MODE_MANUAL):
        raise _bad(ValueError("mode must be 'auto' or 'manual'"))
    try:
        m = chat_api.start_meeting(body.topic, body.participants, body.maxTurns, body.mode, body.hybrid)
    except MeetingError as exc:
        raise _bad(exc, 409 if "already active" in str(exc) else 400)
    _ensure_driver()
    return _ok(m.to_dict())


@router.post("/meeting/next")
async def meeting_next():
    _require_enabled()
    try:
        m = chat_api.meeting_next()
    except MeetingError as exc:
        raise _bad(exc, 409)
    _ensure_driver()
    return _ok(m.to_dict())


@router.post("/meeting/pause")
async def meeting_pause():
    _require_enabled()
    try:
        m = chat_api.meeting_pause()
    except MeetingError as exc:
        raise _bad(exc, 409)
    _cancel_driver()
    return _ok(m.to_dict())


@router.post("/meeting/resume")
async def meeting_resume():
    _require_enabled()
    try:
        m = chat_api.meeting_resume()
    except MeetingError as exc:
        raise _bad(exc, 409)
    _ensure_driver()
    return _ok(m.to_dict())


@router.post("/meeting/stop")
async def meeting_stop():
    _require_enabled()
    try:
        m = chat_api.meeting_stop()
    except MeetingError as exc:
        raise _bad(exc, 409)
    _cancel_driver()
    return _ok(m.to_dict())


@router.get("/health")
async def health():
    data = chat_api.health()
    data["driverActive"] = _driver_task is not None and not _driver_task.done()
    return _ok(data)
