"""
ranking/ranking_history.py — V16 Phase 2 Part 2: ranking persistence

Mirrors scanner/market_scanner.py's _persist/_prune_old_snapshots pattern
exactly (same ManagedConn usage, same one-row-per-cycle JSON-blob shape,
same retention-based pruning) — "use existing database architecture, do
not introduce duplicate persistence layers" means following the pattern
that's already there, not inventing a second one.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from typing import List

from config.settings import settings
from database.db import ManagedConn
from ranking.ranking_models import RankedOpportunity
from utils.logger import get_logger

logger = get_logger(__name__)


def save_ranking(
    ranked: List[RankedOpportunity], symbol_count: int, duration_s: float
) -> None:
    """Persist one ranking cycle. Non-fatal on failure — mirrors
    MarketScanner._persist: a persistence failure must never take down
    the ranking cycle itself or wipe the in-memory result."""
    try:
        avg_coverage = 0.0
        if ranked:
            # coverage isn't stored directly on RankedOpportunity — it's
            # implicit in how many factors are COMPUTED vs UNAVAILABLE in
            # the breakdown; recomputed here cheaply for the summary column.
            from ranking.ranking_models import ScoreStatus
            coverages = []
            for opp in ranked:
                factors = opp.breakdown.factors.values()
                if factors:
                    computed = sum(1 for f in factors if f.status == ScoreStatus.COMPUTED)
                    coverages.append(computed / len(factors))
            avg_coverage = sum(coverages) / len(coverages) if coverages else 0.0

        payload = json.dumps([opp.to_dict() for opp in ranked])
        with ManagedConn() as conn:
            conn.execute(
                "INSERT INTO ranking_history "
                "(timestamp, ranked_at, symbol_count, top_n, avg_coverage, duration_s, data) "
                "VALUES (?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).isoformat(),
                    time.time(),
                    symbol_count,
                    len(ranked),
                    avg_coverage,
                    duration_s,
                    payload,
                ),
            )
            conn.commit()
        _prune_old_rankings()
    except Exception as exc:
        logger.error(f"ranking_history.save_ranking failed (non-fatal, in-memory result still returned): {exc}")


def _prune_old_rankings() -> None:
    try:
        retention_hours = getattr(settings, "RANKER_HISTORY_RETENTION_HOURS", 168)
        cutoff = time.time() - retention_hours * 3600
        with ManagedConn() as conn:
            conn.execute("DELETE FROM ranking_history WHERE ranked_at < ?", (cutoff,))
            conn.commit()
    except Exception as exc:
        logger.debug(f"ranking_history pruning failed (non-fatal): {exc}")


def get_latest_ranking(limit: int = 1) -> List[dict]:
    """Most recent ranking cycle(s), newest first. Returns raw row dicts
    (id, timestamp, ranked_at, symbol_count, top_n, avg_coverage,
    duration_s, data) — `data` is the JSON-decoded list of ranked
    opportunities. Read-only; safe to call from an API handler."""
    from database.db import ReadConn
    try:
        with ReadConn() as conn:
            rows = conn.execute(
                "SELECT id, timestamp, ranked_at, symbol_count, top_n, avg_coverage, duration_s, data "
                "FROM ranking_history ORDER BY ranked_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            d = dict(row) if hasattr(row, "keys") else {
                "id": row[0], "timestamp": row[1], "ranked_at": row[2],
                "symbol_count": row[3], "top_n": row[4], "avg_coverage": row[5],
                "duration_s": row[6], "data": row[7],
            }
            d["data"] = json.loads(d["data"])
            out.append(d)
        return out
    except Exception as exc:
        logger.error(f"ranking_history.get_latest_ranking failed: {exc}")
        return []
