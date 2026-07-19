"""
api/portfolio_api.py — V16 Phase 2C: Portfolio API

REST read layer over portfolio/portfolio_history.py. Additive: an
APIRouter included into the existing api/app.py singleton (same pattern
every other /api/* route in this codebase already uses), not a second
FastAPI app. No exchange calls, no PortfolioManager/CapitalManager
calls, no execution — this module only ever reads rows that Phase 2B's
PortfolioManager already persisted.

Every endpoint returns 200 with an honest empty/null payload when no
decision has ever been persisted (matching the existing convention in
api/app.py — see /api/paper, /api/paper/trades: "disabled/unavailable
is a normal, expected runtime state... NOT a server error"). See
api/portfolio_serializers.py for why every payload also carries an
explicit `source`/`live` marker.

Auth: routes are under /api/portfolio/*, so the existing
_auth_middleware in api/app.py already covers them at the default
VIEWER role — nothing in api/auth.py needed changing.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from portfolio import portfolio_history
from api.portfolio_serializers import (
    serialize_decision,
    serialize_state,
    serialize_allocations,
    serialize_sectors,
    serialize_history_page,
)

router = APIRouter(prefix="/api/portfolio", tags=["portfolio"])


def _ok(data) -> JSONResponse:
    # Mirrors api/app.py's own _ok() envelope shape exactly
    # ({"ok": True, "data": ...}) for response consistency across every
    # /api/* route. Not imported from api.app to avoid a circular import
    # (api/app.py includes this router, so api.app -> api.portfolio_api
    # already; the reverse edge would make it circular) — this is a
    # 3-line helper, not a duplicated manager/business-logic module.
    return JSONResponse(content={"ok": True, "data": data})


def _latest_row() -> Optional[dict]:
    rows = portfolio_history.get_latest_decisions(limit=1)
    return rows[0] if rows else None


@router.get("/state")
async def portfolio_state():
    """Positions implied by the latest persisted decision cycle. See
    portfolio_serializers.serialize_state for why this is explicitly
    NOT a live PortfolioState."""
    return _ok(serialize_state(_latest_row()))


@router.get("/decision/latest")
async def portfolio_decision_latest():
    """The latest persisted OrchestratedDecision in full, unmodified."""
    return _ok(serialize_decision(_latest_row()))


@router.get("/history")
async def portfolio_history_endpoint(
    limit: int = Query(default=50, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    symbol: Optional[str] = Query(default=None),
    sector: Optional[str] = Query(default=None),
):
    """Paginated decision-cycle history, newest first. symbol/sector are
    optional filters (see portfolio_history.query_decisions for exactly
    what each matches)."""
    rows = portfolio_history.query_decisions(
        limit=limit, offset=offset, symbol=symbol, sector=sector,
    )
    # total is only meaningful (and cheap) unfiltered — see
    # serialize_history_page's own docstring for the filtered case.
    total = portfolio_history.count_decisions() if not (symbol or sector) else None
    return _ok(serialize_history_page(rows, total=total, limit=limit, offset=offset))


@router.get("/sectors")
async def portfolio_sectors():
    """Sector exposure + diversification score from the latest persisted
    decision cycle."""
    return _ok(serialize_sectors(_latest_row()))


@router.get("/allocations")
async def portfolio_allocations():
    """Just the `selected` allocation list from the latest persisted
    decision cycle."""
    return _ok(serialize_allocations(_latest_row()))
