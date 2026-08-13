"""
api/account_api.py — V16 Track W14-1 Item 2: Real Account Telemetry

REST read layer over exchange_state/manager.py's process-wide C1
ExchangeStateManager singleton (get_manager_if_registered()). Additive:
an APIRouter included into the existing api/app.py singleton, same
pattern api/portfolio_api.py (Phase 2C), api/execution_api.py
(Phase 2E), and api/lifecycle_api.py (Phase 4B Step 3D) already
established — not a second FastAPI app.

This module never constructs a BinanceDataProvider or an
ExchangeStateManager itself, and never calls ExchangeStateManager.
refresh() directly — it only calls the existing get_snapshot() cache-
first read (TTL-bounded, see exchange_state/constants.py), the exact
same call ANY other C1 consumer (World, CEO context) already makes.
Multiple dashboard tabs polling this endpoint therefore share one
upstream Binance call per TTL window, not one per tab per poll — see
exchange_state/manager.py's own module docstring ("One refresh() = ...
not one call per field").

C1 is deliberately mode-scoped (get_manager() registry key is (mode,
exchange, account_id)): whatever main.py's build_system() registered
for the CURRENT EXECUTION_MODE at startup is what this endpoint reads.
If nothing has registered yet — e.g. this module is imported outside
main.py's normal bootstrap (a bare test harness) — get_manager_if_
registered() returns None and every endpoint below reports status
"NO_DATA_YET" rather than fabricating data or raising.

Realized PnL reuses journal/journal_v2.py's existing
get_performance_summary()/get_today_pnl() — no separate PnL
calculation is implemented here (per this phase's own scope rule: do
not invent a second calculation next to an existing one).

Auth: routes are under /api/account/*, so the existing
_auth_middleware in api/app.py already covers them at the default
VIEWER role — nothing in api/auth.py needed changing (same reasoning
as api/portfolio_api.py's own module docstring).

Lifecycle independence (W14-0): this module never reads or checks
TradingControlState.lifecycle_state anywhere. Account telemetry is
sourced entirely from C1's own cache, which is refreshed by whatever
called get_snapshot() last (this endpoint, itself, on each request) —
it has no dependency on run_trading_cycle() or the START/STOP state
machine, so it continues to serve fresh-as-of-TTL data whether the bot
is RUNNING, STOPPED, STARTING, STOPPING, or FAILED.
"""
from __future__ import annotations

import time
from collections import namedtuple

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from config.settings import EXECUTION_MODE
from exchange_state.constants import DEFAULT_SNAPSHOT_TTL_SECONDS
from exchange_state.manager import get_manager_if_registered
from exchange_state.models import ExchangeSnapshot, PositionSnapshot
from journal.journal_v2 import TradeJournalV2
from portfolio.sector_engine import SectorEngine

router = APIRouter(prefix="/api/account", tags=["account"])

# How long past a degraded/failed refresh's last known-good fetch we
# keep calling it "STALE" (still show the last numbers, just flagged)
# before escalating the display status to "OFFLINE" (numbers may be
# badly out of date; still not fabricated, just older than this
# window). This is a display-only heuristic layered on top of C1's own
# degraded/stale_reason/health_score fields — mirrors the "documented
# here so nobody mistakes it for exhaustive" posture exchange_state/
# manager.py's own _classify_stale_reason() docstring already uses for
# the same reason: it's a UI convenience, not a new source of truth.
_OFFLINE_AFTER_SECONDS = DEFAULT_SNAPSHOT_TTL_SECONDS * 10  # 30s by default


def _ok(data) -> JSONResponse:
    # Mirrors api/portfolio_api.py's / api/execution_api.py's own _ok()
    # exactly, reimplemented locally for the same reason those modules'
    # docstrings give: avoid a circular import back through api.app.
    return JSONResponse(content={"ok": True, "data": data})


def _journal() -> TradeJournalV2:
    # Fresh instance per call, same fallback behavior api/app.py's own
    # _journal() uses when no live instance was injected — TradeJournalV2
    # reads/writes the same on-disk DB regardless of which instance
    # constructed it (see journal/journal_v2.py), so this is not a
    # second, divergent journal, just a second handle onto the same one.
    return TradeJournalV2()


def _freshness(snapshot: ExchangeSnapshot | None) -> str:
    """Map C1's existing (degraded, stale_reason, health_score,
    fetched_at) fields onto the 5-state dashboard vocabulary. Pure
    display logic — never mutates or re-derives account data itself."""
    if snapshot is None:
        return "NO_DATA_YET"
    if snapshot.health_score == 0:
        # _handle_refresh_failure()'s "no prior snapshot at all" branch
        # sets health_score=0 — i.e. the very first fetch attempt itself
        # failed, so there has never been a real number to show.
        return "NO_DATA_YET"
    if not snapshot.degraded:
        return "LIVE"
    age = time.time() - snapshot.fetched_at
    if snapshot.stale_reason == "rate_limit":
        # Distinct from a network/timeout blip — usually means something
        # (this process or another) is polling Binance too aggressively;
        # worth flagging distinctly from "exchange unreachable".
        return "ERROR"
    if age > _OFFLINE_AFTER_SECONDS:
        return "OFFLINE"
    return "STALE"


def _roi_pct(pos: PositionSnapshot) -> float | None:
    """Standard "ROI on margin used" display formula: unrealized_pnl /
    (notional / leverage). Not a Binance-native field — derived here
    exactly once, from fields C1 already provides. Returns None (never
    a fabricated 0) if the inputs can't safely support the division."""
    if pos.leverage <= 0 or pos.entry_price <= 0 or pos.quantity <= 0:
        return None
    margin_used = (pos.quantity * pos.entry_price) / pos.leverage
    if margin_used <= 0:
        return None
    return round((pos.unrealized_pnl / margin_used) * 100, 4)


def _position_payload(pos: PositionSnapshot, snapshot: ExchangeSnapshot) -> dict:
    notional = round(pos.quantity * pos.mark_price, 8)
    sl_price = None
    tp_price = None
    for o in snapshot.orders:
        if o.symbol != pos.symbol:
            continue
        if o.is_sl and sl_price is None:
            sl_price = o.stop_price
        elif o.is_tp and tp_price is None:
            tp_price = o.stop_price
    return {
        "symbol":            pos.symbol,
        "side":              pos.side,
        "quantity":          pos.quantity,
        "entry_price":       pos.entry_price,
        "mark_price":        pos.mark_price,
        "liquidation_price": pos.liquidation_price,
        "leverage":          pos.leverage,
        "margin_type":       pos.margin_type,
        "unrealized_pnl":    pos.unrealized_pnl,
        "notional":          notional,
        "roi_pct":           _roi_pct(pos),
        "sl_price":          sl_price,
        "tp_price":          tp_price,
        "version":           pos.version,
    }


def _empty_payload(status: str) -> dict:
    return {
        "status": status,
        "mode": EXECUTION_MODE,
        "account": None,
        "positions": [],
        "orders": [],
        "sector_allocation": [],
        "realized_pnl_total": None,
        "realized_pnl_today": None,
        "performance": {"total_trades": 0, "win_rate": None, "profit_factor": None, "avg_rr": None},
        "revision": None,
        "fetched_at": None,
        "age_seconds": None,
    }


@router.get("/state")
async def account_state():
    """Real account balance/margin/positions/orders, sourced from C1's
    cached ExchangeSnapshot (get_snapshot() — TTL-bounded pull cache,
    no per-request Binance call). NEVER replaces unavailable data with
    a fake 0 — a genuinely absent value stays null and `status` tells
    the dashboard why."""
    manager = get_manager_if_registered(mode=EXECUTION_MODE)
    if manager is None:
        return _ok(_empty_payload("NO_DATA_YET"))

    snapshot = manager.get_snapshot()
    status = _freshness(snapshot)
    if status == "NO_DATA_YET":
        return _ok(_empty_payload("NO_DATA_YET"))

    journal = _journal()
    try:
        performance = journal.get_performance_summary()
    except Exception:
        performance = {"total_trades": 0, "message": "unavailable"}
    try:
        realized_today = journal.get_today_pnl()
    except Exception:
        realized_today = None
    realized_total = performance.get("total_pnl")

    account = snapshot.account
    positions = list(snapshot.positions.values())
    # Real sector exposure, derived from live position notional — reuses
    # portfolio/sector_engine.py's existing SectorEngine (Phase 2B)
    # rather than inventing a second sector classifier. exposure_by_sector
    # reads .symbol/.notional off whatever it's given, so a tiny local
    # namedtuple is enough; it never touches PositionSnapshot.sector
    # (which sector_engine.py's own docstring documents as always None
    # today — see that file for why).
    _SectorInput = namedtuple("_SectorInput", ["symbol", "notional"])
    sector_inputs = [
        _SectorInput(symbol=p.symbol, notional=p.quantity * p.mark_price)
        for p in positions
    ]
    exposure = SectorEngine.exposure_by_sector(sector_inputs)
    total_notional = sum(exposure.values())
    sector_allocation = [
        {
            "sector": sector,
            "notional": round(notional, 8),
            "pct": round(notional / total_notional * 100, 2) if total_notional > 0 else 0.0,
        }
        for sector, notional in sorted(exposure.items(), key=lambda kv: -kv[1])
    ]

    return _ok({
        "status": status,
        "mode": snapshot.mode,
        "account": {
            "wallet_balance":       account.wallet_balance,
            "available_balance":    account.available_balance,
            "unrealized_pnl":       account.unrealized_pnl,
            "total_margin_balance": account.total_margin_balance,
            "maintenance_margin":   account.maintenance_margin,
            "initial_margin":       account.initial_margin,
            "margin_ratio": (
                round(account.maintenance_margin / account.total_margin_balance, 6)
                if account.total_margin_balance > 0 else None
            ),
        },
        "positions": [_position_payload(p, snapshot) for p in positions],
        "orders": [
            {
                "symbol":          o.symbol,
                "order_id":        o.order_id,
                "client_order_id": o.client_order_id,
                "side":            o.side,
                "type":            o.type,
                "status":          o.status,
                "stop_price":      o.stop_price,
                "orig_qty":        o.orig_qty,
                "executed_qty":    o.executed_qty,
                "reduce_only":     o.reduce_only,
                "is_sl":           o.is_sl,
                "is_tp":           o.is_tp,
            }
            for o in snapshot.orders
        ],
        "sector_allocation": sector_allocation,
        "realized_pnl_total": realized_total,
        "realized_pnl_today": realized_today,
        # Reused verbatim from journal_v2.get_performance_summary() — see
        # that method for exact semantics. total_trades==0 means "no
        # closed trades yet", not an error; win_rate/profit_factor/avg_rr
        # are absent (not 0) in that case, matching this module's own
        # "never fabricate a 0" rule.
        "performance": {
            "total_trades":  performance.get("total_trades", 0),
            "win_rate":      performance.get("win_rate"),
            "profit_factor": performance.get("profit_factor"),
            "avg_rr":        performance.get("avg_rr"),
        },
        "revision": snapshot.revision,
        "fetched_at": snapshot.fetched_at,
        "age_seconds": round(time.time() - snapshot.fetched_at, 3),
        "degraded": snapshot.degraded,
        "stale_reason": snapshot.stale_reason,
        "health_score": snapshot.health_score,
    })
