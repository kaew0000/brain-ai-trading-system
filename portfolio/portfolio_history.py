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
from typing import List

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


def get_latest_decisions(limit: int = 1) -> List[dict]:
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
