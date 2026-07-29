"""
api/lifecycle_api.py — V16 Phase 4B Step 3D: Unified Trade Lifecycle

REST read layer over execution/trade_lifecycle.py's process-wide default
TradeLifecycle (get_default_trade_lifecycle()). Additive: an APIRouter
included into the existing api/app.py singleton, same pattern
api/portfolio_api.py (Phase 2C) and api/execution_api.py (Phase 2E)
already established — not a second FastAPI app.

No exchange calls, no lifecycle-mutating calls (open_pending/
request_exit/etc.) — this module only ever reads whatever the live
TradeLifecycle singleton currently holds. If nothing has ever gone
through it (no scheduler running yet, or nothing open right now), every
endpoint returns 200 with an honest empty payload — same convention
api/portfolio_api.py's and api/execution_api.py's own module docstrings
already document.

Auth: routes are under /api/lifecycle/*, so the existing
_auth_middleware in api/app.py already covers them at the default
VIEWER role — nothing in api/auth.py needed changing.
"""
from __future__ import annotations

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from execution.trade_lifecycle import get_default_trade_lifecycle

router = APIRouter(prefix="/api/lifecycle", tags=["lifecycle"])


def _ok(data) -> JSONResponse:
    # Mirrors api/portfolio_api.py's and api/execution_api.py's own
    # _ok() exactly, reimplemented locally for the same reason those
    # modules' docstrings give: avoid a circular import back through
    # api.app.
    return JSONResponse(content={"ok": True, "data": data})


@router.get("/state")
async def lifecycle_state():
    """Every symbol currently open or in the middle of opening/closing
    right now (Part G: "Current Lifecycle State"). Terminal CLOSED/
    FAILED handles are not included here by design — see
    TradeLifecycle.snapshot()'s own docstring; query
    /api/portfolio/history (Phase 2C) or /api/execution/executions
    (Phase 2E) for closed-trade history, this endpoint is live state
    only."""
    lifecycle = get_default_trade_lifecycle()
    return _ok({"positions": lifecycle.snapshot(), "count": len(lifecycle)})


@router.get("/state/{symbol}")
async def lifecycle_state_for_symbol(symbol: str):
    """One symbol's current lifecycle state — Part G's "Current
    Lifecycle State", "Close Reason", "Source", "Agent Attribution"
    (via confidence — full per-agent attribution lives in the journal,
    not duplicated here, see /api/portfolio/decision/latest and
    /api/execution/executions), "Exit Type" (exit_source) columns, all
    from the one TradeHandle this symbol currently has, if any."""
    lifecycle = get_default_trade_lifecycle()
    state = lifecycle.get_state(symbol)
    if state is None:
        return _ok({
            "symbol": symbol, "state": None, "trade_id": None,
            "exit_reason": None, "exit_source": None, "confidence": None,
            "note": "No live lifecycle handle for this symbol — either "
                    "never opened, or already closed/failed (terminal "
                    "handles are not exposed here by design).",
        })
    rows = [row for row in lifecycle.snapshot() if row["symbol"] == symbol]
    return _ok(rows[0] if rows else {"symbol": symbol, "state": state.value})
