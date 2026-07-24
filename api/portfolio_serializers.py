"""
api/portfolio_serializers.py — V16 Phase 2C: Portfolio API

Pure functions only: turn portfolio_history row dicts (already
JSON-decoded by portfolio/portfolio_history.py) into the exact payload
shapes portfolio_api.py and portfolio_ws.py send over the wire. No
database access, no PortfolioManager/CapitalManager calls, no exchange
calls — this module never constructs a PortfolioDecision/
OrchestratedDecision itself, it only reshapes ones that were already
computed and persisted by Phase 2B's PortfolioManager.decide().

Why every payload carries an explicit `source`/`live` marker
--------------------------------------------------------------
Per the Phase 2C brief: this API must never be mistaken for a live
execution-state feed. There is currently no scheduler calling
PortfolioManager.decide() on a cadence (see architecture.md §19 —
that's future work), so every value here is "whatever the most recent
persisted decision cycle said", which can be arbitrarily stale or
(before any cycle has ever run) simply absent. Rather than relying on
callers to infer that from context, every serializer output includes:

    "source": "latest_persisted_decision"
    "live":    False

so a client (or a human reading a raw response) cannot mistake this for
a continuously-updated live PortfolioState even without reading docs.
"""
from __future__ import annotations


SOURCE_LABEL = "latest_persisted_decision"


def _meta(as_of: str | None = None, note: str | None = None) -> dict:
    return {
        "source": SOURCE_LABEL,
        "live": False,
        "as_of": as_of,
        "note": note or (
            "Reflects the latest persisted PortfolioManager.decide() "
            "cycle, not a continuously live PortfolioState."
        ),
    }


def serialize_decision(row: dict | None) -> dict:
    """GET /api/portfolio/decision/latest and the WS 'decision' event.
    row is one entry from portfolio_history.get_latest_decisions()/
    query_decisions(), or None if nothing has ever been persisted."""
    if row is None:
        return {
            "decision": None,
            **_meta(note="No portfolio decision has ever been persisted yet."),
        }
    return {
        "decision": row["data"],
        **_meta(as_of=row["timestamp"]),
    }


def serialize_state(row: dict | None) -> dict:
    """GET /api/portfolio/state.

    Deliberately NOT a PortfolioState object and NOT named as one in the
    payload — there is no live PortfolioState singleton anywhere in this
    process (see portfolio/portfolio_state.py's own docstring: "who
    constructs and keeps this in sync with reality is explicitly out of
    scope"). What we *can* honestly report is the set of allocations the
    most recent persisted decision selected, which is real, persisted
    data — just presented as exactly what it is: a snapshot of the last
    decision cycle, not a live account view."""
    if row is None:
        return {
            "positions": [],
            "total_capital_allocated": 0.0,
            "total_risk_allocated": 0.0,
            "blocked": None,
            "block_reason": None,
            **_meta(note="No portfolio decision has ever been persisted yet — "
                         "positions is an empty list, not a synthesized state."),
        }
    data = row["data"]
    return {
        "positions": data.get("selected", []),
        "total_capital_allocated": row["total_capital_allocated"],
        "total_risk_allocated": row["total_risk_allocated"],
        "blocked": row["blocked"],
        "block_reason": row["block_reason"],
        **_meta(as_of=row["timestamp"]),
    }


def serialize_allocations(row: dict | None) -> dict:
    """GET /api/portfolio/allocations — just the `selected` list, with
    its own meta so it's usable standalone (e.g. from the WS stream)
    without also shipping rejected/replacements."""
    if row is None:
        return {"allocations": [], **_meta(note="No portfolio decision has ever been persisted yet.")}
    return {
        "allocations": row["data"].get("selected", []),
        **_meta(as_of=row["timestamp"]),
    }


def serialize_sectors(row: dict | None) -> dict:
    """GET /api/portfolio/sectors — sector_exposure + diversification_score
    from the latest persisted decision. sector_exposure here is
    SectorEngine.exposure_by_sector() (notional-based), exactly as
    architecture.md §18 documents it — not the capital-based figure
    that enforces max_sector_pct."""
    if row is None:
        return {
            "sector_exposure": {},
            "diversification_score": None,
            **_meta(note="No portfolio decision has ever been persisted yet."),
        }
    return {
        "sector_exposure": row["data"].get("sector_exposure", {}),
        "diversification_score": row["diversification_score"],
        **_meta(as_of=row["timestamp"]),
    }


def serialize_history_entry(row: dict) -> dict:
    """One row of GET /api/portfolio/history's `entries` list — a
    condensed view (not the full `data` blob) so a page of N history
    entries doesn't ship N full decision payloads. Full detail for any
    one cycle is available by cross-referencing decided_at against
    /api/portfolio/decision/latest, or by widening limit/offset."""
    return {
        "decided_at": row["decided_at"],
        "timestamp": row["timestamp"],
        "blocked": row["blocked"],
        "block_reason": row["block_reason"],
        "selected_count": row["selected_count"],
        "rejected_count": row["rejected_count"],
        "replacement_count": row["replacement_count"],
        "total_capital_allocated": row["total_capital_allocated"],
        "total_risk_allocated": row["total_risk_allocated"],
        "diversification_score": row["diversification_score"],
        "portfolio_score": row["portfolio_score"],
        "symbols": sorted({a["symbol"] for a in row["data"].get("selected", [])}),
    }


def serialize_history_page(
    rows: list[dict],
    total: int | None,
    limit: int,
    offset: int,
) -> dict:
    """GET /api/portfolio/history full payload, pagination metadata
    included so a client can page without a second count call.

    total is None when a symbol/sector filter was applied — filtering
    happens in Python over decoded JSON (see
    portfolio_history.query_decisions), so there's no cheap exact count
    of *matching* rows without decoding the whole table; rather than
    fabricate one, total/has_more fall back to an honest best-effort
    (has_more True only when a full page was returned)."""
    has_more = (offset + len(rows) < total) if total is not None else (len(rows) == limit and limit > 0)
    return {
        "entries": [serialize_history_entry(r) for r in rows],
        "pagination": {
            "limit": limit,
            "offset": offset,
            "returned": len(rows),
            "total": total,
            "has_more": has_more,
        },
        **_meta(),
    }
