"""
Brain Bot BTCUSDT — Dashboard API  (Phase 4C + v14 Phase 2 Telemetry)
=======================================================================

REST endpoints
--------------
GET  /api/health             — liveness + uptime
GET  /api/config              — read-only settings
GET  /api/decision            — latest ConfidenceResult
GET  /api/signals              — recent signal history
GET  /api/futures              — OI / funding / L-S snapshot
GET  /api/regime               — market regime history
GET  /api/events                — recent EventBus messages
GET  /api/journal                — closed trade journal (performance summary + trades)
GET  /api/paper                   — paper trading metrics + open positions
GET  /api/agents                   — latest report from every AI agent + CEO decision
GET  /api/agents/telemetry          — v14: status/confidence/latency/uptime per agent
GET  /api/agents/{name}              — full report for a single agent
GET  /api/agents/{name}/memory        — last N reports from an agent
POST /api/chat                         — interactive agent chat
POST /api/auth/token                   — P1-A: exchange API key for bearer token
POST /api/auth/rotate                  — P1-A: rotate the caller's bearer token

GET  /api/portfolio/state              — V16 Phase 2C: latest persisted decision's positions (not live)
GET  /api/portfolio/decision/latest    — V16 Phase 2C: latest persisted OrchestratedDecision
GET  /api/portfolio/history            — V16 Phase 2C: paginated decision history (limit/offset/symbol/sector)
GET  /api/portfolio/sectors            — V16 Phase 2C: sector exposure + diversification score
GET  /api/portfolio/allocations        — V16 Phase 2C: latest persisted allocation list

WebSocket streams
-----------------
WS   /ws/events        — EventBus fan-out (every new event)
WS   /ws/signals       — new signals as they arrive
WS   /ws/decision      — latest decision on every cycle tick
WS   /ws/agents        — v14: agent telemetry snapshot, pushed ~1 Hz
WS   /ws/portfolio     — V16 Phase 2C: new persisted portfolio decisions + 5s heartbeat

Run standalone
--------------
    python -m api.app
    # or via uvicorn:
    uvicorn api.app:app --host 0.0.0.0 --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Query, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
import os as _os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from config.settings import settings
from api.auth import (
    Role, AuthError, authenticate_request, enforce_ws_role,
    issue_token_for_api_key, rotate_token, log_unauthorized,
)
from events.event_bus import get_event_bus
from journal.journal_v2 import TradeJournalV2
from telemetry.agent_telemetry import get_telemetry_registry
from reasoning.reasoning_stream import get_reasoning_stream
from graph.agent_graph import build_agent_graph
from intelligence.market_intelligence_service import get_market_intelligence_service
from missions.mission_tracker import get_mission_tracker, STAGES as MISSION_STAGES
from commander.commander_service import CommanderService
from commander.control_state import get_control_state
from system_health.watchdog import get_watchdog
from system_health.reconciliation import get_reconciliation_engine
from system_health.recovery_engine import get_recovery_engine
from utils.logger import get_logger

# V16 Phase 2C — Portfolio API (REST + WebSocket). See api/portfolio_api.py
# and api/portfolio_ws.py module docstrings for design rationale.
from api.portfolio_api import router as _portfolio_router
from api.portfolio_ws import router as _portfolio_ws_router
from api.portfolio_ws import check_and_broadcast as _portfolio_ws_check

# V16 Phase 2E — Execution API. See api/execution_api.py's module
# docstring for design rationale (same additive-router pattern as
# Phase 2C above).
from api.execution_api import router as _execution_router

logger = get_logger("api.app")

# ── Startup time ──────────────────────────────────────────────────────────────
_STARTED_AT = datetime.now(timezone.utc)

# ── Shared state (set by main.py or paper runner) ─────────────────────────────
# These are set at runtime by the caller; API reads them safely.
_state: Dict[str, Any] = {
    "latest_decision":   None,   # ConfidenceResult or dict
    "latest_context":    None,   # market_context dict
    "paper_engine":      None,   # PaperExecutionEngine instance
    "journal_v2":        None,   # TradeJournalV2 instance
}
# V15: RLock guards compound read-modify operations across threads.
# Single-key writes are GIL-safe but multi-key snapshots need a lock.
import threading as _threading
_state_lock = _threading.RLock()


def set_state(key: str, value: Any) -> None:
    """Thread-safe single-key update (called from trading loop)."""
    with _state_lock:
        _state[key] = value


def get_state(key: str, default: Any = None) -> Any:
    """Thread-safe read of a single state key."""
    with _state_lock:
        return _state.get(key, default)


# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    """Fan-out broadcaster for a single WS channel."""

    def __init__(self) -> None:
        self._clients: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._clients.add(ws)
        logger.debug(f"WS client connected ({len(self._clients)} total)")

    def disconnect(self, ws: WebSocket) -> None:
        self._clients.discard(ws)
        logger.debug(f"WS client disconnected ({len(self._clients)} remaining)")

    async def broadcast(self, data: dict) -> None:
        dead: List[WebSocket] = []
        msg = json.dumps(data)
        for client in list(self._clients):
            try:
                await client.send_text(msg)
            except Exception:
                dead.append(client)
        for d in dead:
            self._clients.discard(d)

    @property
    def count(self) -> int:
        return len(self._clients)


_ws_events   = ConnectionManager()
_ws_signals  = ConnectionManager()
_ws_decision = ConnectionManager()
_ws_agents   = ConnectionManager()   # v14 Phase 2 — agent telemetry stream
_ws_missions = ConnectionManager()   # v14 Phase 2.5 — mission pipeline stream
_ws_command  = ConnectionManager()   # v14 Phase 2.5 — commander command/response stream


# ── Background broadcaster ────────────────────────────────────────────────────

_last_event_seq = 0   # tracks last broadcast EventBus seq (fix: was "id",
                       # a field BusEvent never had, so this comparison was
                       # always 0 > 0 and no event was ever broadcast)

# ── Content-hash dedup for 1Hz push channels ──────────────────────────────────
# These channels push every loop tick regardless of whether the data changed.
# Sending identical payloads triggers a Zustand state update → full React
# re-render every second → visible flicker on all animated components.
# Fix: cache a hash of the last-sent payload per channel; skip the broadcast
# when the hash is unchanged.  We hash the semantically-meaningful fields only
# (exclude `timestamp` which always changes).
import hashlib as _hashlib

def _payload_hash(data: dict, exclude_keys: tuple = ("timestamp",)) -> str:
    """Return a short hash of `data` ignoring `exclude_keys`."""
    filtered = {k: v for k, v in data.items() if k not in exclude_keys}
    raw = json.dumps(filtered, sort_keys=True, default=str)
    return _hashlib.md5(raw.encode()).hexdigest()[:12]

_last_decision_hash:  str = ""
_last_missions_hash:  str = ""
_last_telemetry_hash: str = ""

async def _broadcast_loop() -> None:
    """
    Polls EventBus every second and fans out new events to WebSocket clients.

    Also beats the "websocket" heartbeat every tick so the Watchdog never
    reports it as DEAD.  The heartbeat records the number of connected WS
    clients so the dashboard can show a meaningful "last seen" timestamp
    even when zero clients are connected.

    V15.1 anti-flicker: decision / telemetry / missions channels are now
    content-hash-deduped.  A frame is only broadcast when the payload has
    actually changed since the last push.  This eliminates the 1Hz Zustand
    state update that caused every React component on the dashboard to
    re-render every second.
    """
    global _last_event_seq, _last_decision_hash, _last_missions_hash, _last_telemetry_hash
    while True:
        await asyncio.sleep(1)
        try:
            # ── Websocket subsystem heartbeat ─────────────────────────────────
            try:
                from system_health.heartbeat import get_heartbeat
                get_heartbeat().beat("websocket", meta={
                    "ws_events":   _ws_events.count,
                    "ws_decision": _ws_decision.count,
                    "ws_agents":   _ws_agents.count,
                    "ws_missions": _ws_missions.count,
                    "ws_ml":       _ws_ml.count,
                })
                # Bug fix: dashboard_api was only beaten once at bootstrap
                # (build_system(), before the API server even started), so
                # with a 30s DEAD threshold the watchdog reported it DEAD
                # for the entire lifetime of every run after the first ~60s
                # — even while it was actively serving this dashboard. A
                # tick of this loop is direct proof the API's event loop is
                # alive, so beat it here every second alongside "websocket".
                get_heartbeat().beat("dashboard_api", meta={
                    "ws_events": _ws_events.count,
                })
            except Exception:
                pass

            bus = _BUS_INSTANCE or get_event_bus()
            recent = bus.get_recent(limit=50)

            new_events  = [e for e in recent if e.get("seq", 0) > _last_event_seq]
            new_signals = [e for e in new_events if e.get("event") == "TRADE_DECISION"]

            if new_events:
                _last_event_seq = max(e.get("seq", 0) for e in new_events)

            for ev in reversed(new_events):
                await _ws_events.broadcast({"type": "event", "data": ev})

            for sig in reversed(new_signals):
                await _ws_signals.broadcast({"type": "signal", "data": sig})

            # ── /ws/decision — only push when decision actually changed ────────
            if _state["latest_decision"] is not None:
                dec = _state["latest_decision"]
                payload = dec.to_dict() if hasattr(dec, "to_dict") else dec
                h = _payload_hash(payload if isinstance(payload, dict) else {})
                if h != _last_decision_hash:
                    _last_decision_hash = h
                    await _ws_decision.broadcast({
                        "type":      "decision",
                        "data":      payload,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            # ── /ws/agents — only push when telemetry changed ─────────────────
            if _ws_agents.count > 0:
                registry = get_telemetry_registry()
                snap = registry.snapshot()
                h = _payload_hash(snap if isinstance(snap, dict) else {})
                if h != _last_telemetry_hash:
                    _last_telemetry_hash = h
                    await _ws_agents.broadcast({
                        "type":      "telemetry",
                        "data":      snap,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

            # ── /ws/portfolio — V16 Phase 2C: heartbeat + new-decision-only
            # broadcast, entirely inside this same existing loop tick (see
            # api/portfolio_ws.py's module docstring for why this isn't a
            # second independent poll loop).
            try:
                await _portfolio_ws_check()
            except Exception as exc:
                logger.debug(f"portfolio WS check_and_broadcast error: {exc}")

            # ── /ws/missions — only push when missions changed ────────────────
            if _ws_missions.count > 0:
                tracker = get_mission_tracker()
                active  = tracker.get_active()
                h = _payload_hash({"missions": active} if isinstance(active, list) else (active or {}))
                if h != _last_missions_hash:
                    _last_missions_hash = h
                    await _ws_missions.broadcast({
                        "type":      "missions",
                        "data":      active,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        except Exception as exc:
            logger.debug(f"broadcast_loop error: {exc}")


# ── App lifecycle ─────────────────────────────────────────────────────────────

# ── Dashboard static files ─────────────────────────────────────────────────
_DASHBOARD_DIR = _os.path.join(_os.path.dirname(_os.path.dirname(__file__)), "dashboard")

async def _supervised_broadcast() -> None:
    """V15: Self-restarting wrapper for the broadcast loop.
    If _broadcast_loop() crashes, logs the error and restarts after 2s.
    Without this, a single uncaught exception kills the loop permanently."""
    while True:
        try:
            await _broadcast_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(f"broadcast loop crashed, restarting in 2s: {exc}", exc_info=True)
            await asyncio.sleep(2)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(_supervised_broadcast())
    logger.info("Dashboard API V15 started — supervised broadcast loop running")
    yield
    task.cancel()
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
    except (asyncio.CancelledError, asyncio.TimeoutError):
        pass
    logger.info("Dashboard API shutdown")


# ── FastAPI app ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="Brain Bot BTCUSDT Dashboard API",
    version="4C",
    description="Real-time dashboard for Brain Bot v13 Phase 4C",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# V16 Phase 2C — Portfolio API. /api/portfolio/* routes are covered by the
# existing _auth_middleware below automatically (any path starting with
# "/api/" that isn't in _AUTH_PUBLIC_PATHS defaults to VIEWER role) — no
# auth changes needed. /ws/portfolio enforces its own VIEWER role the same
# way every other /ws/* handler in this file does.
app.include_router(_portfolio_router)
app.include_router(_portfolio_ws_router)

# V16 Phase 2E — Execution API. /api/execution/* is covered by the SAME
# prefix-generic _auth_middleware — no auth changes needed here either.
app.include_router(_execution_router)


# ── P1-A: Dashboard authentication ─────────────────────────────────────────
# Public (no auth required regardless of API_AUTH_ENABLED): the SPA shell
# pages (they render client-side and hit these same /api/* routes for real
# data, so protecting the HTML shell adds no security), static assets,
# the liveness probe, and the token-exchange endpoint itself (you need to
# be able to reach it unauthenticated to get a token in the first place).
_AUTH_PUBLIC_PATHS = {
    "/", "/dashboard", "/agents", "/debate", "/missions", "/portfolio",
    "/intelligence", "/memory", "/replay", "/commander", "/health", "/world",
    "/api/health", "/api/auth/token",
}
# (METHOD, path) pairs that require OPERATOR rather than VIEWER. Everything
# else under /api/ defaults to VIEWER. WebSocket routes are handled
# separately in each handler via enforce_ws_role() — Starlette HTTP
# middleware does not run for the websocket ASGI scope.
_AUTH_OPERATOR_ROUTES = {
    ("POST", "/api/command"),
}


@app.middleware("http")
async def _auth_middleware(request: Request, call_next):
    if not settings.API_AUTH_ENABLED:
        return await call_next(request)

    path = request.url.path
    if path in _AUTH_PUBLIC_PATHS or path.startswith("/assets"):
        return await call_next(request)
    if not path.startswith("/api/"):
        # Any other non-API route (e.g. an SPA deep link not in the list
        # above) — serve the shell, same as before this patch.
        return await call_next(request)

    client = request.client.host if request.client else "?"
    try:
        ctx = authenticate_request(request)
    except AuthError as exc:
        log_unauthorized(path, request.method, client, exc.reason)
        return JSONResponse({"ok": False, "error": exc.reason}, status_code=exc.status_code)

    min_role = Role.OPERATOR if (request.method, path) in _AUTH_OPERATOR_ROUTES else Role.VIEWER
    if ctx.role < min_role:
        log_unauthorized(path, request.method, client, f"role {ctx.role.name} < required {min_role.name}")
        return JSONResponse({"ok": False, "error": "insufficient role"}, status_code=403)

    request.state.auth = ctx
    return await call_next(request)


if not settings.API_AUTH_ENABLED:
    logger.warning(
        "API_AUTH_ENABLED=false — the dashboard API has NO authentication. "
        "Every /api/* and /ws/* endpoint, including POST /api/command "
        "(pause/resume live trading), is reachable by anyone who can reach "
        "this host. Set API_AUTH_ENABLED=true and configure API_KEYS + "
        "JWT_SECRET before exposing this beyond localhost."
    )
else:
    logger.info(f"API authentication ENABLED ({len(settings.API_KEYS)} API key(s) configured)")


# ── Helpers ───────────────────────────────────────────────────────────────────

# Injected instances (set by main.py _start_api_server)
_JOURNAL_INSTANCE: "TradeJournalV2 | None" = None
_BUS_INSTANCE:     "Any | None"            = None
_COMMANDER = CommanderService()   # v14 Phase 2.5 — stateless, safe as module singleton


def _build_commander_context() -> dict:
    """
    Build the read-only context dict CommanderService needs for
    "show positions/pnl/risk" commands, sourced fresh from live _state
    on every call so results are never stale.
    """
    paper_engine = _state.get("paper_engine")
    data_provider = _state.get("data_provider")
    risk_engine = _state.get("risk_engine")

    position_info = None
    if paper_engine is None and data_provider is not None:
        try:
            position_info = data_provider.get_position_info()
        except Exception as exc:
            logger.debug(f"Commander context: position_info fetch failed: {exc}")

    risk_report = None
    if risk_engine is not None:
        try:
            balance = data_provider.get_account_balance() if data_provider else 0.0
            risk_report = risk_engine.report(balance)
        except Exception as exc:
            logger.debug(f"Commander context: risk_report build failed: {exc}")

    return {
        "paper_engine":  paper_engine,
        "position_info": position_info,
        "journal_v2":    _journal(),
        "risk_report":   risk_report,
    }


def _journal() -> TradeJournalV2:
    """Return the injected journal (from trading loop) or a fresh one."""
    if _JOURNAL_INSTANCE is not None:
        return _JOURNAL_INSTANCE
    return _state.get("journal_v2") or TradeJournalV2()


def _ok(data: dict | list, status: int = 200) -> JSONResponse:
    return JSONResponse(content={"ok": True, "data": data}, status_code=status)


def _uptime_s() -> int:
    return int((datetime.now(timezone.utc) - _STARTED_AT).total_seconds())


# ═════════════════════════════════════════════════════════════════════════════
# REST Endpoints
# ═════════════════════════════════════════════════════════════════════════════

# v14 Phase 4 — serve Vite-built React SPA from dashboard/dist/
# Falls back to dashboard/index.html (legacy CDN version) if dist not present
_DASHBOARD_DIST = _os.path.join(_DASHBOARD_DIR, "dist")

# Mount Vite built static assets (JS/CSS chunks) from dist/assets/
_DASHBOARD_ASSETS = _os.path.join(_DASHBOARD_DIST, "assets")
if _os.path.exists(_DASHBOARD_ASSETS):
    app.mount("/assets", StaticFiles(directory=_DASHBOARD_ASSETS), name="dashboard-assets")

@app.get("/", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
@app.get("/agents", include_in_schema=False)
@app.get("/debate", include_in_schema=False)
@app.get("/missions", include_in_schema=False)
@app.get("/portfolio", include_in_schema=False)
@app.get("/intelligence", include_in_schema=False)
@app.get("/memory", include_in_schema=False)
@app.get("/replay", include_in_schema=False)
@app.get("/commander", include_in_schema=False)
@app.get("/health", include_in_schema=False)
@app.get("/world", include_in_schema=False)  # V15: World HQ 2D game page
async def serve_dashboard():
    """
    Serve the Brain Bot V15 React Command Office + World HQ dashboard.
    Tries dist/ (Vite production build) first, falls back to legacy index.html.
    All SPA routes return the same index.html so React Router handles them client-side.
    """
    dist_index = _os.path.join(_DASHBOARD_DIST, "index.html")
    if _os.path.exists(dist_index):
        return FileResponse(dist_index, media_type="text/html")
    legacy = _os.path.join(_DASHBOARD_DIR, "index.html")
    if _os.path.exists(legacy):
        return FileResponse(legacy, media_type="text/html")
    return HTMLResponse("<h1 style=\'font-family:monospace;color:#00ff88;background:#070714;padding:40px\'>Brain Bot V14 API is running. Dashboard not found at: " + dist_index + "</h1>")


@app.get("/api/health")
async def health():
    """Liveness probe + uptime."""
    bus       = get_event_bus()
    jrn       = _journal()
    pe        = _state.get("paper_engine")
    paper_ok  = pe is not None
    perf      = jrn.get_performance_summary() if paper_ok else {}

    return _ok({
        "status":            "ok",
        "version":           "v13-phase4c",
        "symbol":            settings.SYMBOL,
        "leverage":          settings.LEVERAGE,
        "testnet":           settings.BINANCE_TESTNET,
        "uptime_s":          _uptime_s(),
        "started_at":        _STARTED_AT.isoformat(),
        "event_bus_clients": _ws_events.count,
        "agent_ws_clients":  _ws_agents.count,
        "mode":              _os.environ.get("EXECUTION_MODE", "paper").lower(),
        "paper_enabled":     paper_ok,
        "paper_trades":      perf.get("total_trades", 0),
        "time_drift_ms":     getattr(_state.get("data_provider"), "_time_drift_ms", 0),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    })


@app.post("/api/auth/token")
async def auth_token(body: dict):
    """
    P1-A — Exchange an API key for a short-lived bearer token.

    Body: { "api_key": "..." }
    Returns: { "token": str, "role": "admin"|"operator"|"viewer",
               "expires_at": <unix ts>, "jti": str }

    This route is reachable even when the caller has no token yet — it IS
    the login step. It's still subject to whatever's in front of this
    process (reverse proxy rate limiting, etc.); this app doesn't add its
    own rate limiting here to avoid inventing a second, uncoordinated
    limiter on top of one you may already run at the proxy layer.
    """
    result = issue_token_for_api_key((body or {}).get("api_key", ""))
    if result is None:
        log_unauthorized("/api/auth/token", "POST", "-", "invalid API key")
        raise HTTPException(status_code=401, detail="invalid API key")
    return _ok(result)


@app.post("/api/auth/rotate")
async def auth_rotate(request: Request):
    """
    P1-A — Rotate the caller's own bearer token: revoke the presented one,
    issue a fresh one with the same role. Requires a currently-valid
    Bearer token (not an API key — API keys are rotated by editing
    API_KEYS in config, not through this endpoint).
    """
    if not settings.API_AUTH_ENABLED:
        raise HTTPException(status_code=400, detail="API_AUTH_ENABLED is false")
    auth_header = request.headers.get("authorization", "")
    token = auth_header.split(" ", 1)[1].strip() if auth_header.lower().startswith("bearer ") else ""
    if not token:
        raise HTTPException(status_code=401, detail="rotate requires an existing Bearer token")
    try:
        return _ok(rotate_token(token))
    except AuthError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.reason)


@app.get("/api/config")
async def config():
    """Read-only subset of settings (no secrets)."""
    return _ok({
        "symbol":                  settings.SYMBOL,
        "leverage":                settings.LEVERAGE,
        "testnet":                 settings.BINANCE_TESTNET,
        "loop_interval_s":         settings.LOOP_INTERVAL,
        "trade_threshold":         settings.TRADE_THRESHOLD,
        "wait_threshold":          settings.WAIT_THRESHOLD,
        "risk_per_trade_min":      settings.RISK_PER_TRADE_MIN,
        "risk_per_trade_max":      settings.RISK_PER_TRADE_MAX,
        "max_daily_loss":          settings.MAX_DAILY_LOSS,
        "max_consecutive_losses":  settings.MAX_CONSECUTIVE_LOSSES,
        "funding_block_long":      settings.FUNDING_BLOCK_LONG,
        "funding_block_short":     settings.FUNDING_BLOCK_SHORT,
        "default_rr":              settings.DEFAULT_RR,
        "oi_rising_strong":        settings.OI_RISING_STRONG,
        "volume_spike_multiplier": settings.VOLUME_SPIKE_MULTIPLIER,
    })


@app.get("/api/decision")
async def decision():
    """Latest ConfidenceResult / decision cycle output."""
    dec = _state.get("latest_decision")
    ctx = _state.get("latest_context")

    if dec is None:
        return _ok({
            "message":   "No decision yet — bot not started or first cycle pending",
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })

    payload = dec.to_dict() if hasattr(dec, "to_dict") else dict(dec)

    # Augment with last signal from journal
    jrn = _journal()
    sig = jrn.get_latest_signal(symbol=settings.SYMBOL)
    explanation = jrn.get_latest_explanation(symbol=settings.SYMBOL)

    return _ok({
        "decision":    payload,
        "signal":      sig,
        "explanation": explanation,
        "context_keys": list(ctx.keys()) if ctx else [],
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/signals")
async def signals(
    limit:  int = Query(default=50,  ge=1, le=500),
    symbol: str = Query(default=""),
):
    """Recent decision-cycle signals (all actions, not just trades)."""
    jrn  = _journal()
    sym  = symbol or settings.SYMBOL
    rows = jrn.get_signals(limit=limit, symbol=sym)
    return _ok({
        "symbol":  sym,
        "count":   len(rows),
        "signals": rows,
    })


@app.get("/api/futures")
async def futures(
    limit:  int = Query(default=50, ge=1, le=500),
    symbol: str = Query(default=""),
):
    """OI history + funding history + latest futures context."""
    jrn = _journal()
    sym = symbol or settings.SYMBOL

    oi      = jrn.get_oi_history(limit=limit,      symbol=sym)
    funding = jrn.get_funding_history(limit=limit,  symbol=sym)
    ctx     = _state.get("latest_context") or {}

    futures_ctx = ctx.get("futures", {})

    return _ok({
        "symbol":          sym,
        "oi_history":      oi,
        "funding_history": funding,
        "snapshot": {
            "oi_delta":          ctx.get("oi_delta",           0.0),
            "funding_rate":      ctx.get("funding_rate",       0.0),
            "mark_price":        ctx.get("mark_price",         0.0),  # BUG-V15-FE-01: was missing; Overview.tsx crashed on .toLocaleString()
            "futures_signal":    ctx.get("futures_signal",     ""),
            "futures_condition": ctx.get("futures_condition",  ""),
            "futures_detail":    futures_ctx,
        },
    })


@app.get("/api/intelligence")
async def market_intelligence(refresh_fear_greed: bool = Query(default=False)):
    """
    v14 Phase 2.5 — Unified Market Intelligence Feed.

    Combines five sources into one payload:
      funding / open_interest / liquidations  — pure reads from the live
        FuturesIntelEngine output (_state["latest_context"]), zero extra
        computation or network calls.
      fear_greed          — fetched from alternative.me, cached 10 min.
      economic_calendar    — stub (no free public API); returns
        available=False until a real provider is configured.

    Query params
    ------------
    refresh_fear_greed : bypass the 10-minute fear_greed cache and fetch fresh.
    """
    ctx = _state.get("latest_context") or {}
    service = get_market_intelligence_service()

    payload = {
        "funding":           service.get_funding(ctx),
        "open_interest":     service.get_open_interest(ctx),
        "liquidations":      service.get_liquidations(ctx),
        "fear_greed":        service.get_fear_greed(force_refresh=refresh_fear_greed),
        "economic_calendar": service.get_economic_calendar(),
        "timestamp":         datetime.now(timezone.utc).isoformat(),
    }
    return _ok(payload)


@app.get("/api/missions")
async def missions(
    stage:       Optional[str] = Query(default=None),
    limit:       int  = Query(default=50, ge=1, le=500),
    active_only: bool = Query(default=False),
):
    """
    v14 Phase 2.5 — Mission Pipeline.

    Lists trade missions tracked through their lifecycle:
    SIGNAL_FOUND → VALIDATION → RISK_CHECK → EXECUTION → MONITORING → CLOSED.
    Data source for the future Mission Board Kanban dashboard page.

    Query params
    ------------
    stage       : filter to one exact stage (e.g. "MONITORING")
    limit       : max missions to return (ignored when active_only=true)
    active_only : if true, return only non-CLOSED missions (ideal for a
                  live Kanban board — closed missions belong in the
                  Journal Intelligence / Trade Replay pages instead)
    """
    tracker = get_mission_tracker()
    if active_only:
        data = tracker.get_active()
    else:
        data = tracker.list(stage=stage, limit=limit)

    return _ok({
        "missions":     data,
        "mission_count": len(data),
        "stages":        MISSION_STAGES,
        "timestamp":     datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/missions/{mission_id}")
async def mission_detail(mission_id: str):
    """Full lifecycle detail (including history timeline) for one mission."""
    tracker = get_mission_tracker()
    mission = tracker.get(mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail=f"Mission '{mission_id}' not found")
    return _ok(mission.to_dict())


@app.get("/api/regime")
async def regime(
    limit:  int = Query(default=50,  ge=1, le=500),
    symbol: str = Query(default=""),
):
    """Market regime history + current regime."""
    jrn = _journal()
    sym = symbol or settings.SYMBOL

    history = jrn.get_market_regimes(limit=limit, symbol=sym)
    latest  = history[0] if history else None
    ctx     = _state.get("latest_context") or {}

    return _ok({
        "symbol":  sym,
        "current": {
            "regime":        ctx.get("regime",        latest.get("regime",     "") if latest else ""),
            "confidence":    ctx.get("regime_conf",   latest.get("confidence", 0.0) if latest else 0.0),
            "trend_bias":    ctx.get("trend_bias",    ""),
            "trend_strength": ctx.get("trend_strength", ""),
            "trend_data":    ctx.get("trend_data",    {}),
        },
        "count":   len(history),
        "history": history,
    })


@app.get("/api/events")
async def events(
    limit:  int          = Query(default=50,  ge=1, le=200),
    agent:  Optional[str] = Query(default=None),
    event:  Optional[str] = Query(default=None),
):
    """Recent EventBus messages with optional agent/event filter."""
    bus  = get_event_bus()
    rows = bus.get_recent(limit=limit, agent=agent)

    if event:
        rows = [r for r in rows if r.get("event") == event]

    return _ok({
        "count":  len(rows),
        "events": rows,
        "ws_clients": _ws_events.count,
    })


@app.get("/api/journal")
async def journal(
    limit:  int = Query(default=50,  ge=1, le=500),
    symbol: str = Query(default=""),
):
    """Closed trades + performance summary + causal explanations."""
    jrn = _journal()
    sym = symbol or settings.SYMBOL

    perf         = jrn.get_performance_summary(limit=limit)
    daily        = jrn.get_daily_stats()
    open_trades  = jrn.get_open_trades()
    explanations = jrn.get_explanations(limit=10, symbol=sym)
    agent_msgs   = jrn.get_agent_messages(limit=20)

    return _ok({
        "symbol":       sym,
        "performance":  perf,
        "daily":        daily,
        "open_trades":  open_trades,
        "explanations": explanations,
        "agent_messages": agent_msgs,
    })


@app.get("/api/paper")
async def paper():
    """Paper trading metrics + open positions + equity curve."""
    pe = _state.get("paper_engine")
    if pe is None:
        return _ok({
            "enabled":  False,
            "message":  "Paper trading engine not running",
        })

    metrics   = pe.get_metrics()
    positions = pe.get_open_positions()
    trades    = pe.get_closed_trades(limit=200)
    curve     = pe.account.equity_curve[-100:]   # last 100 points

    return _ok({
        "enabled":        True,
        "metrics":        metrics,
        "open_positions": positions,
        "recent_trades":  trades[-20:],
        "trade_count":    pe.trade_count,
        "equity_curve":   curve,
        "goal_trades":    200,
        "goal_progress":  round(pe.trade_count / 200 * 100, 1),
    })


@app.get("/api/paper/trades")
async def paper_trades(
    limit: int = Query(default=200, ge=1, le=1000),
):
    """Full closed-trade list from the paper engine.

    Paper trading being disabled/unavailable is a normal, expected runtime
    state (e.g. EXECUTION_MODE=testnet/live, or the engine hasn't finished
    initializing yet) — NOT a server error. We always return 200 with an
    `enabled` flag so the dashboard can render a clean empty state instead
    of treating this as a backend failure.
    """
    pe = _state.get("paper_engine")
    if pe is None:
        return _ok({
            "enabled":     False,
            "trades":      None,
            "total_count": 0,
            "reason":      "Paper trading not initialized",
        })
    return _ok({
        "enabled":     True,
        "trades":      pe.get_closed_trades(limit=limit),
        "total_count": pe.trade_count,
        "reason":      None,
    })


@app.get("/api/paper/metrics")
async def paper_metrics():
    """Just the performance metrics dict.

    Mirrors /api/paper/trades: when the paper engine isn't running we
    return a 200 with enabled=False rather than a 503. A 503 implies the
    *server* is unavailable/overloaded, which triggers client-side retry
    storms; "paper trading isn't configured for this run" is normal,
    steady-state information, not an outage.
    """
    pe = _state.get("paper_engine")
    if pe is None:
        return _ok({
            "enabled": False,
            "metrics": None,
            "reason":  "Paper trading not initialized",
        })
    return _ok({
        "enabled": True,
        "metrics": pe.get_metrics(),
        "reason":  None,
    })


# ═════════════════════════════════════════════════════════════════════════════
# WebSocket Endpoints
# ═════════════════════════════════════════════════════════════════════════════

@app.websocket("/ws/events")
async def ws_events(ws: WebSocket):
    """Fan-out stream of all EventBus events in real-time."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_events.connect(ws)
    try:
        # Send buffered recent events on connect
        bus    = _BUS_INSTANCE or get_event_bus()
        recent = bus.get_recent(limit=20)
        await ws.send_text(json.dumps({
            "type":   "init",
            "events": list(reversed(recent)),
        }))
        while True:
            await ws.receive_text()   # keep-alive; client can send ping
    except WebSocketDisconnect:
        _ws_events.disconnect(ws)
    except Exception:
        _ws_events.disconnect(ws)


@app.websocket("/ws/signals")
async def ws_signals(ws: WebSocket):
    """Stream new TRADE_DECISION signals only."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_signals.connect(ws)
    try:
        # Always send init frame on connect (signal may be None when DB is empty)
        jrn = _journal()
        sig = jrn.get_latest_signal(symbol=settings.SYMBOL)
        await ws.send_text(json.dumps({"type": "init", "signal": sig}))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_signals.disconnect(ws)
    except Exception:
        _ws_signals.disconnect(ws)


@app.websocket("/ws/decision")
async def ws_decision(ws: WebSocket):
    """Pushes latest ConfidenceResult on every cycle (1 Hz poll)."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_decision.connect(ws)
    try:
        # Always send init frame on connect (decision may be None before first cycle)
        dec = _state.get("latest_decision")
        payload = (dec.to_dict() if hasattr(dec, "to_dict") else dec) if dec is not None else None
        await ws.send_text(json.dumps({
            "type":      "init",
            "decision":  payload,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_decision.disconnect(ws)
    except Exception:
        _ws_decision.disconnect(ws)


@app.websocket("/ws/agents")
async def ws_agents(ws: WebSocket):
    """
    v14 Phase 2 — Agent Telemetry Stream.

    Pushes the full TelemetryRegistry snapshot every ~1s (driven by
    _broadcast_loop). Always sends an init frame on connect — even when
    the registry is empty (no agents have run yet) — so clients never
    hang waiting for the first frame (same fix pattern as BUG-06 in
    the v13 audit).
    """
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_agents.connect(ws)
    try:
        registry = get_telemetry_registry()
        await ws.send_text(json.dumps({
            "type":      "init",
            "data":      registry.snapshot(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_agents.disconnect(ws)
    except Exception:
        _ws_agents.disconnect(ws)


@app.websocket("/ws/missions")
async def ws_missions(ws: WebSocket):
    """
    v14 Phase 2.5 — Mission Pipeline Stream.

    Pushes the list of active (non-CLOSED) missions every ~1s. Always
    sends an init frame on connect, even when no missions exist yet
    (empty list) — same BUG-06-safe pattern as every other WS endpoint
    in this file.
    """
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_missions.connect(ws)
    try:
        tracker = get_mission_tracker()
        await ws.send_text(json.dumps({
            "type":      "init",
            "data":      tracker.get_active(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_missions.disconnect(ws)
    except Exception:
        _ws_missions.disconnect(ws)


@app.websocket("/ws/command")
async def ws_command(ws: WebSocket):
    """
    v14 Phase 2.5 — Commander Interface Stream (bidirectional).

    Unlike the other WS endpoints, this one is interactive: the client
    sends text frames containing JSON {"command": "pause trader"} (or a
    bare command string), the server executes it via the same
    CommanderService used by POST /api/command, and replies with the
    CommandResult over the same socket. The result is also broadcast to
    every other connected /ws/command client so multiple open dashboard
    tabs stay in sync.

    Always sends an init frame on connect — the current control-state
    snapshot — so clients immediately know paused/paper_mode_forced
    status without waiting for a command (BUG-06-safe pattern).
    """
    if await enforce_ws_role(ws, Role.OPERATOR) is None:
        return
    await _ws_command.connect(ws)
    try:
        await ws.send_text(json.dumps({
            "type":      "init",
            "data":      get_control_state().snapshot(),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            raw = await ws.receive_text()
            try:
                payload = json.loads(raw)
                command_text = payload.get("command", "") if isinstance(payload, dict) else str(payload)
            except (json.JSONDecodeError, AttributeError):
                command_text = raw

            context = _build_commander_context()
            result = _COMMANDER.execute(command_text, context=context)
            frame = {"type": "command_result", "data": result.to_dict()}

            # The sender is already part of _ws_command's client set (added by
            # connect() above), so a single broadcast delivers the result to
            # the sender AND every other open dashboard tab — sending a
            # separate direct reply here would duplicate the message.
            await _ws_command.broadcast(frame)

    except WebSocketDisconnect:
        _ws_command.disconnect(ws)
    except Exception:
        _ws_command.disconnect(ws)




# ── Phase 3C — ML WebSocket ───────────────────────────────────────────────────

_ws_ml = ConnectionManager()


@app.websocket("/ws/ml")
async def ws_ml(ws: WebSocket):
    """Push ML advisor status at 2s intervals."""
    if await enforce_ws_role(ws, Role.VIEWER) is None:
        return
    await _ws_ml.connect(ws)
    try:
        # Send init frame
        try:
            from ml.ml_advisor import get_ml_advisor
            status = get_ml_advisor().status()
        except Exception:
            status = {}
        await ws.send_text(json.dumps({
            "type": "init", "status": status,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        _ws_ml.disconnect(ws)
    except Exception:
        _ws_ml.disconnect(ws)


# ═════════════════════════════════════════════════════════════════════════════
# Agent Layer Endpoints (Phase 2 — AI Employee Layer)
# ═════════════════════════════════════════════════════════════════════════════

@app.get("/api/agents/graph")
async def agents_graph():
    """
    v14 Phase 2.5 — Agent Relationship Graph.

    Returns the CEO + 6 sub-agent dependency tree in React Flow node/edge
    format, ready for direct rendering on the future Agent Floor dashboard
    page. Edge weights come from the live CEOAgent.WEIGHTS when the bot is
    running, falling back to the known-correct static topology otherwise
    — the endpoint always returns a valid, non-empty graph.
    """
    agent_layer = _state.get("agent_layer", {})
    graph = build_agent_graph(agent_layer)
    return _ok(graph)


@app.get("/api/agents")
async def agents_status():
    """Latest report from every AI agent + CEO decision."""
    agent_layer = _state.get("agent_layer", {})
    ceo_decision = _state.get("ceo_decision")

    reports = {}
    for name, agent in agent_layer.items():
        rep = getattr(agent, "last_report", None)
        if rep is not None:
            reports[name] = rep.to_dict()

    ceo_dict = ceo_decision.to_dict() if ceo_decision is not None else {}

    return _ok({
        "agents":       reports,
        "ceo_decision": ceo_dict,
        "agent_count":  len(reports),
        "timestamp":    datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/agents/telemetry")
async def agents_telemetry(spec_only: bool = Query(default=False)):
    """
    v14 Phase 2 — Agent Telemetry snapshot (REST polling alternative to WS /ws/agents).

    Returns the latest {agent: status, confidence, last_signal, latency_ms,
    decision, timestamp, ...} for every agent that has run at least once.

    Query params
    ------------
    spec_only : if true, returns only the exact 7-field spec schema
                (agent/status/confidence/last_signal/latency_ms/decision/timestamp)
                with no extra fields (uptime_s/run_count/error_count omitted).
    """
    registry = get_telemetry_registry()
    snapshot = registry.snapshot_spec() if spec_only else registry.snapshot()
    return _ok({
        "telemetry":   snapshot,
        "agent_count": len(snapshot),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/agents/reasoning")
async def agents_reasoning(
    limit: int = Query(default=50, ge=1, le=500),
    agent: Optional[str] = Query(default=None),
    latest_only: bool = Query(default=False),
):
    """
    v14 Phase 2.5 — Agent Reasoning Stream.

    Data source for the future Agent Debate Room dashboard page: every
    agent's {thought, reasoning, decision, confidence} side-by-side so a
    human can follow WHY the CEO reached its final decision.

    Query params
    ------------
    limit       : max entries to return (ignored when latest_only=true)
    agent       : filter to a single agent's entries (e.g. "SMC_ANALYST")
    latest_only : if true, return only the single most-recent entry per
                  agent (ideal for a "current debate snapshot" view)
    """
    stream = get_reasoning_stream()
    if latest_only:
        data = stream.get_latest_all()
        if agent:
            data = {agent: data[agent]} if agent in data else {}
        return _ok({
            "reasoning":   data,
            "agent_count": len(data),
            "timestamp":   datetime.now(timezone.utc).isoformat(),
        })

    entries = stream.get_recent(limit=limit, agent=agent)
    return _ok({
        "reasoning":   entries,
        "entry_count": len(entries),
        "timestamp":   datetime.now(timezone.utc).isoformat(),
    })


@app.get("/api/agents/{agent_name}")
async def agent_detail(agent_name: str):
    """Full report for a single agent."""
    agent_layer = _state.get("agent_layer", {})
    agent = agent_layer.get(agent_name.lower())
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    rep = getattr(agent, "last_report", None)
    mem = agent.get_memory(n=20) if hasattr(agent, "get_memory") else []
    return _ok({
        "agent":   agent_name,
        "report":  rep.to_dict() if rep else {},
        "memory":  mem,
    })


@app.get("/api/agents/{agent_name}/memory")
async def agent_memory(
    agent_name: str,
    n: int = Query(default=20, ge=1, le=100),
):
    """Last N reports from an agent."""
    agent_layer = _state.get("agent_layer", {})
    agent = agent_layer.get(agent_name.lower())
    if agent is None:
        raise HTTPException(status_code=404, detail=f"Agent '{agent_name}' not found")
    return _ok({"agent": agent_name, "memory": agent.get_memory(n=n)})


@app.get("/api/command/state")
async def command_state():
    """
    v14 Phase 2.5 — Current Commander control flags.

    Returns the live {paused, paper_mode_forced, updated_at} snapshot —
    useful for the dashboard to reflect pause/safety-override state
    without needing to issue a command.
    """
    return _ok(get_control_state().snapshot())


@app.post("/api/command")
async def command(body: dict):
    """
    v14 Phase 2.5 — Commander Interface.

    Body: { "command": "pause trader" }

    Supported commands (exact phrases, case-insensitive, extra words OK):
      pause trader / resume trader / paper mode on / paper mode off /
      show positions / show pnl / show risk

    Returns a CommandResult: { command, matched, success, message, data, timestamp }.
    Unrecognised commands return success=false with a helpful message
    rather than an HTTP error — this is meant to be safe to wire directly
    to a chat-style frontend without special-casing failures.
    """
    command_text = (body or {}).get("command", "")
    context = _build_commander_context()
    result = _COMMANDER.execute(command_text, context=context)

    # Broadcast every executed command to connected /ws/command clients so
    # multiple open dashboard tabs stay in sync.
    if _ws_command.count > 0:
        try:
            await _ws_command.broadcast({"type": "command_result", "data": result.to_dict()})
        except Exception as exc:
            logger.debug(f"Command broadcast skipped: {exc}")

    return _ok(result.to_dict())


@app.post("/api/chat")
async def agent_chat(body: dict):
    """
    Interactive chat with an AI agent.

    Body: { "agent": "smc" | "ceo" | ..., "question": "Why LONG?" }
    Returns: { "agent": str, "answer": str, "signal": str, "confidence": float }
    """
    agent_layer  = _state.get("agent_layer", {})
    agent_name   = (body.get("agent") or "ceo").lower()
    question     = (body.get("question") or "").strip()
    market_ctx   = _state.get("latest_context") or {}

    if not question:
        raise HTTPException(status_code=400, detail="question is required")

    # Route to CEO which delegates to the right agent
    ceo = agent_layer.get("ceo")
    target = agent_layer.get(agent_name)

    answer_text = ""
    if target is not None:
        answer_text = target.answer(question, market_ctx)
    elif ceo is not None:
        answer_text = ceo.answer(question, market_ctx)
    else:
        answer_text = "Agent layer not running. Start the bot first."

    rep = getattr(target or ceo, "last_report", None)
    return _ok({
        "agent":      agent_name,
        "question":   question,
        "answer":     answer_text,
        "signal":     rep.signal     if rep else "UNKNOWN",
        "confidence": rep.confidence if rep else 0.0,
        "timestamp":  datetime.now(timezone.utc).isoformat(),
    })


# ── Phase 3A — System Health endpoints ───────────────────────────────────────

@app.get("/api/system/health")
async def system_health():
    """V15: System health with circuit breaker status."""
    """Watchdog snapshot: per-subsystem ALIVE/STALE/DEAD + overall status."""
    try:
        snap = get_watchdog().snapshot()
        return _ok(snap)
    except Exception as exc:
        logger.error(f"/api/system/health error: {exc}", exc_info=True)
        return _ok({"subsystems": {}, "overall_status": "UNKNOWN",
                    "timestamp": datetime.now(timezone.utc).isoformat(), "error": str(exc)})


@app.get("/api/system/reconciliation")
async def system_reconciliation(limit: int = Query(default=50, ge=1, le=200)):
    """Position reconciliation history + recovery log."""
    try:
        engine = get_reconciliation_engine()
        recovery = get_recovery_engine()
        return _ok({
            "status":       engine.status(),
            "events":       engine.get_recent(limit=limit),
            "recovery_log": recovery.get_attempt_log(limit=limit),
            "timestamp":    datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error(f"/api/system/reconciliation error: {exc}", exc_info=True)
        return _ok({"status": {}, "events": [], "recovery_log": [],
                    "timestamp": datetime.now(timezone.utc).isoformat(), "error": str(exc)})


# ── Phase 3C — ML endpoints ───────────────────────────────────────────────────

@app.get("/api/ml/status")
async def ml_status():
    """MLAdvisor current status: active models, last prediction."""
    try:
        from ml.ml_advisor import get_ml_advisor
        return _ok(get_ml_advisor().status())
    except Exception as exc:
        logger.error(f"/api/ml/status error: {exc}", exc_info=True)
        return _ok({"error": str(exc), "timestamp": datetime.now(timezone.utc).isoformat()})


@app.get("/api/ml/models")
async def ml_models(limit: int = Query(default=50, ge=1, le=200)):
    """List all registered ML models (all types, all versions)."""
    try:
        from ml.model_registry import get_model_registry
        reg = get_model_registry()
        return _ok({
            "meta_label":          reg.list_models("meta_label",          limit=limit),
            "confidence_calibrator": reg.list_models("confidence_calibrator", limit=limit),
            "outcome_predictor":    reg.list_models("outcome_predictor",   limit=limit),
            "timestamp":           datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error(f"/api/ml/models error: {exc}", exc_info=True)
        return _ok({"error": str(exc)})


@app.get("/api/ml/performance")
async def ml_performance():
    """Active model metrics + dataset stats."""
    try:
        from ml.model_registry import get_model_registry
        from research.dataset_builder import get_dataset_builder
        reg = get_model_registry()
        builder = get_dataset_builder()
        return _ok({
            "active_models": {
                "meta_label":          reg.get_active("meta_label"),
                "confidence_calibrator": reg.get_active("confidence_calibrator"),
                "outcome_predictor":    reg.get_active("outcome_predictor"),
            },
            "dataset": {
                "total_rows":    builder.row_count(labelled_only=False),
                "labelled_rows": builder.row_count(labelled_only=True),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as exc:
        logger.error(f"/api/ml/performance error: {exc}", exc_info=True)
        return _ok({"error": str(exc)})


@app.get("/api/forward_test")
async def forward_test():
    """Latest forward test performance report."""
    pe = _state.get("paper_engine")
    ev = _state.get("forward_evaluator")

    trades = []
    if pe is not None:
        try:
            trades = pe.get_closed_trades(limit=1000)
        except Exception:
            pass

    from forward_test.evaluator import ForwardTestEvaluator
    evaluator = ev or ForwardTestEvaluator()
    report    = evaluator.evaluate(trades)
    return _ok({
        "report":       report.to_dict(),
        "summary_line": report.summary_line(),
        "trade_count":  len(trades),
    })

# ── Standalone entry ──────────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
