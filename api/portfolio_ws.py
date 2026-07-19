"""
api/portfolio_ws.py — V16 Phase 2C: Portfolio API

WebSocket stream at /ws/portfolio. Deliberately has no polling loop or
scheduler of its own — `check_and_broadcast()` is called once per tick
from api/app.py's existing, already-supervised `_broadcast_loop()` (the
same single loop every other WS channel in this codebase already rides
on: /ws/decision, /ws/agents, /ws/missions). Adding a second independent
poll loop here would be exactly the kind of duplicate-scheduler
infrastructure "No Scheduler" in the Phase 2C brief rules out; hooking
into the existing one is the additive, "follow existing architecture"
option.

Streams ONLY newly persisted decisions — see check_and_broadcast()'s
dedup-by-row-id logic below. If nothing new has been persisted since the
last tick (including "nothing has ever been persisted"), the stream
sends only its heartbeat and stays otherwise idle, per the brief's rule
5 ("If nothing is persisted, the stream simply remains idle").
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import List, Optional, Set

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from portfolio import portfolio_history
from api.auth import Role, enforce_ws_role
from api.portfolio_serializers import (
    serialize_decision,
    serialize_state,
    serialize_sectors,
    serialize_allocations,
)
from utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL_SECONDS = 5

# ── Connection tracking ──────────────────────────────────────────────────
# Same minimal per-channel ConnectionManager pattern api/app.py already
# uses 7 times over (one instance per WS channel) — not a shared/reused
# class here to avoid the api.app <-> api.portfolio_ws circular import
# that would come from importing api.app.ConnectionManager (api/app.py
# is the one that includes this router).
_clients: Set[WebSocket] = set()

# Dedup state — module-level because it tracks "has this cycle already
# been broadcast to everyone", not anything per-connection.
_last_broadcast_row_id: Optional[int] = None
_last_heartbeat_at: float = 0.0


async def _broadcast(message: dict) -> None:
    if not _clients:
        return
    raw = json.dumps(message)
    dead: List[WebSocket] = []
    for client in list(_clients):
        try:
            await client.send_text(raw)
        except Exception:
            dead.append(client)
    for d in dead:
        _clients.discard(d)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _send_init_frame(ws: WebSocket) -> None:
    """Reconnect-safe: every new connection immediately gets the current
    latest-persisted-decision snapshot (or explicit nulls if nothing has
    ever been persisted), regardless of the global broadcast-dedup
    state — so a client reconnecting mid-stream never has to wait for
    the next new decision to know where things stand."""
    rows = portfolio_history.get_latest_decisions(limit=1)
    row = rows[0] if rows else None
    await ws.send_text(json.dumps({
        "type": "init",
        "decision": serialize_decision(row),
        "state": serialize_state(row),
        "sectors": serialize_sectors(row),
        "allocations": serialize_allocations(row),
        "timestamp": _now_iso(),
    }))


@router.websocket("/ws/portfolio")
async def ws_portfolio(ws: WebSocket):
    """Streams: decision, state, sectors, allocations, replacement_proposal
    events (only when a new decision cycle is persisted) plus a heartbeat
    every 5s. Same VIEWER-role auth as every other /ws/* channel in this
    codebase (api/auth.enforce_ws_role)."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await ws.accept()
    _clients.add(ws)
    logger.debug(f"WS /ws/portfolio client connected ({len(_clients)} total)")
    try:
        await _send_init_frame(ws)
        while True:
            await ws.receive_text()  # keep-alive; client may send ping
    except WebSocketDisconnect:
        _clients.discard(ws)
    except Exception:
        _clients.discard(ws)
    finally:
        logger.debug(f"WS /ws/portfolio client disconnected ({len(_clients)} remaining)")


async def check_and_broadcast() -> None:
    """Called once per tick (~1s) by api/app.py's existing
    _broadcast_loop(). Two independent things happen here, each on its
    own cadence:

    1. Heartbeat, every HEARTBEAT_INTERVAL_SECONDS, regardless of
       whether anything new was persisted — lets a connected client
       detect a silently-dead connection vs. a genuinely idle portfolio.
    2. New-decision broadcast, only when portfolio_history's newest row
       id differs from the last one we already broadcast. This is the
       ENTIRE duplicate-prevention mechanism: a row id can only newly
       appear once, so re-running this check every tick against an
       unchanged newest id is a guaranteed no-op — no separate
       already-sent set, no time-window heuristic.
    """
    global _last_broadcast_row_id, _last_heartbeat_at

    now = time.time()
    if now - _last_heartbeat_at >= HEARTBEAT_INTERVAL_SECONDS:
        _last_heartbeat_at = now
        await _broadcast({"type": "heartbeat", "timestamp": _now_iso()})

    if not _clients:
        return

    rows = portfolio_history.get_latest_decisions(limit=1)
    if not rows:
        return  # nothing persisted yet — stream stays idle apart from heartbeat
    row = rows[0]
    if row["id"] == _last_broadcast_row_id:
        return  # already broadcast this cycle — stay idle, no duplicate

    _last_broadcast_row_id = row["id"]

    await _broadcast({"type": "decision", "data": serialize_decision(row), "timestamp": _now_iso()})
    await _broadcast({"type": "state", "data": serialize_state(row), "timestamp": _now_iso()})
    await _broadcast({"type": "sectors", "data": serialize_sectors(row), "timestamp": _now_iso()})
    await _broadcast({"type": "allocations", "data": serialize_allocations(row), "timestamp": _now_iso()})

    for proposal in row["data"].get("replacements", []):
        await _broadcast({"type": "replacement_proposal", "data": proposal, "timestamp": _now_iso()})


def client_count() -> int:
    """Exposed for tests and for api/app.py's heartbeat meta (mirrors
    ConnectionManager.count elsewhere in api/app.py)."""
    return len(_clients)


def _reset_for_tests() -> None:  # pragma: no cover
    """Test-only: clear module-level dedup/heartbeat state between test
    cases, since it's intentionally module-level (see check_and_broadcast
    docstring) rather than per-connection."""
    global _last_broadcast_row_id, _last_heartbeat_at
    _last_broadcast_row_id = None
    _last_heartbeat_at = 0.0
    _clients.clear()
