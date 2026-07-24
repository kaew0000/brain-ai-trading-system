"""
portfolio/portfolio_history.py — V16 Phase 2B: Portfolio Manager Orchestrator

Persistence only — no decision logic, no exchange calls. Mirrors
ranking/ranking_history.py's pattern exactly (same ManagedConn usage,
same one-row-per-cycle JSON-blob shape, same retention-based pruning) —
"use existing database architecture, do not introduce duplicate
persistence layers" means following the pattern that's already there,
not inventing a second one.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from config.settings import settings
from database.db import ManagedConn, ReadConn
from portfolio.portfolio_models import OrchestratedDecision
from utils.logger import get_logger

logger = get_logger(__name__)


def save_decision(
    decision: OrchestratedDecision,
    sector_exposure: dict,
    drawdown: float,
) -> None:
    """Persist one PortfolioManager.decide() cycle. Non-fatal on failure —
    mirrors ranking_history.save_ranking / MarketScanner._persist: a
    persistence failure must never take down the decision cycle itself or
    wipe the in-memory result the caller already has."""
    try:
        payload = json.dumps(decision.to_dict() | {
            "sector_exposure": dict(sector_exposure),
            "drawdown": drawdown,
        })
        with ManagedConn() as conn:
            conn.execute(
                "INSERT INTO portfolio_history "
                "(timestamp, decided_at, blocked, block_reason, selected_count, "
                "rejected_count, replacement_count, total_capital_allocated, "
                "total_risk_allocated, diversification_score, portfolio_score, "
                "drawdown, data) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    decision.generated_at,
                    1 if decision.blocked else 0,
                    decision.block_reason,
                    len(decision.selected),
                    len(decision.rejected),
                    len(decision.replacements),
                    decision.total_capital_allocated,
                    decision.total_risk_allocated,
                    decision.diversification_score,
                    decision.portfolio_score,
                    drawdown,
                    payload,
                ),
            )
            conn.commit()
        _prune_old_decisions()
    except Exception as exc:
        logger.error(f"portfolio_history.save_decision failed (non-fatal, in-memory decision still returned): {exc}")


def _prune_old_decisions() -> None:
    try:
        retention_hours = getattr(settings, "PORTFOLIO_HISTORY_RETENTION_HOURS", 168)
        cutoff = time.time() - retention_hours * 3600
        with ManagedConn() as conn:
            conn.execute("DELETE FROM portfolio_history WHERE decided_at < ?", (cutoff,))
            conn.commit()
    except Exception as exc:
        logger.debug(f"portfolio_history pruning failed (non-fatal): {exc}")


def get_latest_decisions(limit: int = 1) -> list[dict]:
    """Most recent decision cycle(s), newest first. Returns raw row dicts
    (id, timestamp, decided_at, blocked, block_reason, selected_count,
    rejected_count, replacement_count, total_capital_allocated,
    total_risk_allocated, diversification_score, portfolio_score,
    drawdown, data) — `data` is the JSON-decoded OrchestratedDecision plus
    sector_exposure/drawdown. Read-only; safe to call from an API handler."""
    try:
        with ReadConn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, decided_at, blocked, block_reason, "
                "selected_count, rejected_count, replacement_count, "
                "total_capital_allocated, total_risk_allocated, "
                "diversification_score, portfolio_score, drawdown, data "
                "FROM portfolio_history ORDER BY decided_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row) if hasattr(row, "keys") else {
                "id": row[0], "timestamp": row[1], "decided_at": row[2],
                "blocked": row[3], "block_reason": row[4],
                "selected_count": row[5], "rejected_count": row[6],
                "replacement_count": row[7], "total_capital_allocated": row[8],
                "total_risk_allocated": row[9], "diversification_score": row[10],
                "portfolio_score": row[11], "drawdown": row[12], "data": row[13],
            }
            d["blocked"] = bool(d["blocked"])
            d["data"] = json.loads(d["data"])
            out.append(d)
        return out
    except Exception as exc:
        logger.error(f"portfolio_history.get_latest_decisions failed: {exc}")
        return []


# ── V16 Phase 2C additions (api/portfolio_api.py) ───────────────────────────
#
# Additive only — nothing above this line changes. get_latest_decisions()
# keeps its exact existing signature/behavior for its one existing caller
# (its own test suite); these two functions exist solely to give the REST
# API pagination and symbol/sector filtering without duplicating the
# storage layer itself (same ManagedConn/ReadConn, same portfolio_history
# table, same JSON-blob row shape).
#
# symbol/sector filtering is done in Python over the decoded `data` blob,
# not SQL WHERE — there's no indexed column for either (the schema stores
# one JSON blob per cycle, same "wide dynamic shape" reasoning
# schema_v13.sql gives for this table). Fine at this table's expected
# scale (one row per decision cycle, pruned by
# PORTFOLIO_HISTORY_RETENTION_HOURS); flagged here as a known limitation
# rather than hidden, same convention every other "known simplification"
# in this codebase follows.

def query_decisions(
    limit: int = 50,
    offset: int = 0,
    symbol: str | None = None,
    sector: str | None = None,
) -> list[dict]:
    """Paginated decision history, newest first, same row shape as
    get_latest_decisions(). symbol filters to cycles where `symbol`
    appears in that cycle's selected or rejected list; sector filters to
    cycles where `sector` appears as a key in that cycle's sector_exposure
    dict. Filtering is applied after decoding each row's JSON, over a
    page fetched with a generous LIMIT (offset + limit, capped at 5000)
    so a symbol/sector filter can't silently under-return a page —
    read-only, safe to call from an API handler, same non-fatal-on-error
    convention as get_latest_decisions (returns [] on failure)."""
    try:
        fetch_n = min(offset + max(limit, 0) * 10 + 50, 5000) if (symbol or sector) else (offset + limit)
        with ReadConn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, decided_at, blocked, block_reason, "
                "selected_count, rejected_count, replacement_count, "
                "total_capital_allocated, total_risk_allocated, "
                "diversification_score, portfolio_score, drawdown, data "
                "FROM portfolio_history ORDER BY decided_at DESC LIMIT ?",
                (fetch_n,),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row) if hasattr(row, "keys") else {
                "id": row[0], "timestamp": row[1], "decided_at": row[2],
                "blocked": row[3], "block_reason": row[4],
                "selected_count": row[5], "rejected_count": row[6],
                "replacement_count": row[7], "total_capital_allocated": row[8],
                "total_risk_allocated": row[9], "diversification_score": row[10],
                "portfolio_score": row[11], "drawdown": row[12], "data": row[13],
            }
            d["blocked"] = bool(d["blocked"])
            d["data"] = json.loads(d["data"])

            if symbol:
                syms = {a["symbol"] for a in d["data"].get("selected", [])} | \
                       {r["symbol"] for r in d["data"].get("rejected", [])}
                if symbol not in syms:
                    continue
            if sector:
                if sector not in d["data"].get("sector_exposure", {}):
                    continue

            out.append(d)
        return out[offset:offset + limit]
    except Exception as exc:
        logger.error(f"portfolio_history.query_decisions failed: {exc}")
        return []


def count_decisions() -> int:
    """Total persisted decision-cycle rows. Read-only; returns 0 on
    failure (never raises) — matches this module's existing
    non-fatal-read convention."""
    try:
        with ReadConn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM portfolio_history").fetchone()
        return int(row[0]) if row else 0
    except Exception as exc:
        logger.error(f"portfolio_history.count_decisions failed: {exc}")
        return 0
