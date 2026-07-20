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

V16 Phase 2E addition — execution event relay
------------------------------------------------------------------------
execution/execution_orchestrator.py publishes execution_started/
completed/failed/cancelled/metrics_updated through the existing
events.event_bus.EventBus (see execution/execution_events.py) rather
than a second pub/sub mechanism. _relay_execution_events(), called from
the SAME check_and_broadcast() tick, dedups by BusEvent.seq (a
monotonic counter EventBus already maintains) exactly the way the
decision broadcast above dedups by row id — no second poll loop, no
protocol redesign, same /ws/portfolio connection and message envelope
({"type": ..., "data": ..., "timestamp": ...}).
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
from events.event_bus import get_event_bus
from execution.execution_events import EXECUTION_AGENT
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

# V16 Phase 2E: separate dedup pointer for the execution-event relay —
# a distinct BusEvent.seq stream from portfolio_history's row ids, so it
# gets its own last-broadcast marker rather than overloading the
# decision one.
_last_broadcast_execution_seq: int = 0


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

    # V16 Phase 2E: independent of the decision-broadcast path below —
    # execution events happen on their own cadence (a batch can span
    # many ticks after the decision that triggered it was already
    # broadcast, or several ticks with no new decision at all), so this
    # must NOT be nested inside the row-id-changed branch below, or it
    # would only ever run in the one tick a decision also happened to
    # change in.
    await _relay_execution_events()

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


async def _relay_execution_events() -> None:
    """V16 Phase 2E: forward any new EXECUTION_AGENT events since the
    last tick. Same dedup shape as the decision broadcast above (compare
    against a last-seen marker, advance it, no separate already-sent
    set) but keyed on BusEvent.seq instead of a portfolio_history row
    id. Gated behind the SAME `if not _clients: return` in
    check_and_broadcast() the decision-broadcast path already uses —
    the dedup pointer does not advance while no one is connected,
    exactly mirroring how _last_broadcast_row_id also doesn't advance
    in that situation.

    Unlike the decision path, _send_init_frame() does NOT include any
    execution snapshot on connect (by design — it only ever composes
    decision/state/sectors/allocations; see that function's own
    docstring). A client that connects after missing some execution
    events gets nothing about them here until the next NEW one fires —
    api/execution_api.py's GET /api/execution/metrics and /status are
    the actual catch-up mechanism for current execution state, not this
    WebSocket."""
    global _last_broadcast_execution_seq

    recent = get_event_bus().get_recent(limit=50, agent=EXECUTION_AGENT)
    if not recent:
        return
    # get_recent() returns newest-first; broadcast in chronological order.
    new_events = [e for e in reversed(recent) if e["seq"] > _last_broadcast_execution_seq]
    if not new_events:
        return

    for event in new_events:
        _last_broadcast_execution_seq = max(_last_broadcast_execution_seq, event["seq"])
        await _broadcast({
            "type": event["event"],       # execution_started / _completed / _failed / _cancelled / _metrics_updated
            "data": event["payload"],
            "timestamp": event["timestamp"],
        })


def client_count() -> int:
    """Exposed for tests and for api/app.py's heartbeat meta (mirrors
    ConnectionManager.count elsewhere in api/app.py)."""
    return len(_clients)


def _reset_for_tests() -> None:  # pragma: no cover
    """Test-only: clear module-level dedup/heartbeat state between test
    cases, since it's intentionally module-level (see check_and_broadcast
    docstring) rather than per-connection."""
    global _last_broadcast_row_id, _last_heartbeat_at, _last_broadcast_execution_seq
    _last_broadcast_row_id = None
    _last_heartbeat_at = 0.0
    _last_broadcast_execution_seq = 0
    _clients.clear()
