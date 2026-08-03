"""
api/world_ws.py — Phase W10: Live Command Center UI (backend layer)

WebSocket stream at /ws/world. Deliberately has no polling loop or
scheduler of its own — check_and_broadcast() is called once per tick from
api/app.py's existing, already-supervised _broadcast_loop(), the same
single loop /ws/decision, /ws/agents, /ws/missions, and /ws/portfolio
already ride on (see api/portfolio_ws.py's module docstring — this file
mirrors that pattern exactly).

Streams the current Phase W7 SimulationState only when its tick number
changes (world.simulation's own `SimulationState.sequence`-gated cache
already means "unchanged" is the common case when nothing in the trading
engine is moving) plus a heartbeat every 5s, matching
api/portfolio_ws.py's dedup discipline: no separate already-sent set, no
time-window heuristic — a tick number can only newly appear once.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from api.auth import Role, enforce_ws_role
from utils.logger import get_logger
from world.simulation import api as simulation_api

logger = get_logger(__name__)

router = APIRouter()

HEARTBEAT_INTERVAL_SECONDS = 5

_clients: set[WebSocket] = set()
_last_broadcast_tick: int | None = None
_last_heartbeat_at: float = 0.0


async def _broadcast(message: dict) -> None:
    if not _clients:
        return
    raw = json.dumps(message)
    dead: list[WebSocket] = []
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
    simulation state, regardless of the global broadcast-dedup state."""
    state = simulation_api.get_simulation_state()
    await ws.send_text(json.dumps({
        "type": "init",
        "data": state.to_dict(),
        "timestamp": _now_iso(),
    }))


@router.websocket("/ws/world")
async def ws_world(ws: WebSocket):
    """Streams the current SimulationState (only when its tick changes)
    plus a heartbeat every 5s. Same VIEWER-role auth as every other
    /ws/* channel in this codebase (api/auth.enforce_ws_role)."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await ws.accept()
    _clients.add(ws)
    logger.debug(f"WS /ws/world client connected ({len(_clients)} total)")
    try:
        await _send_init_frame(ws)
        while True:
            await ws.receive_text()  # keep-alive; client may send ping
    except WebSocketDisconnect:
        _clients.discard(ws)
    except Exception:
        _clients.discard(ws)
    finally:
        logger.debug(f"WS /ws/world client disconnected ({len(_clients)} remaining)")


async def check_and_broadcast() -> None:
    """Called once per tick (~1s) by api/app.py's existing
    _broadcast_loop(). Never calls world.simulation.api.step() itself —
    only reads whatever the trading-bot-driven tick already produced
    (see main.py's world_simulation_tick scheduled job), so this stays a
    pure read-and-relay, same as every other channel on this loop."""
    global _last_broadcast_tick, _last_heartbeat_at

    now = time.time()
    if now - _last_heartbeat_at >= HEARTBEAT_INTERVAL_SECONDS:
        _last_heartbeat_at = now
        await _broadcast({"type": "heartbeat", "timestamp": _now_iso()})

    if not _clients:
        return

    state = simulation_api.get_simulation_state()
    if state.tick.tick_number == _last_broadcast_tick:
        return  # already broadcast this tick — stay idle, no duplicate

    _last_broadcast_tick = state.tick.tick_number
    await _broadcast({"type": "simulation", "data": state.to_dict(), "timestamp": _now_iso()})


def _reset_for_tests() -> None:  # pragma: no cover
    """Test-only: clear module-level dedup/heartbeat state between test
    cases, since it's intentionally module-level (see check_and_broadcast
    docstring) rather than per-connection."""
    global _last_broadcast_tick, _last_heartbeat_at
    _last_broadcast_tick = None
    _last_heartbeat_at = 0.0
    _clients.clear()
