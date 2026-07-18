"""research/feature_store.py — Phase 3B: CRUD against feature_rows table"""
from __future__ import annotations
import json, sqlite3
from datetime import datetime, timezone
from typing import List, Optional
from database.db import ManagedConn, get_db_path
from utils.logger import get_logger
logger = get_logger(__name__)

FEATURE_COLUMNS = (
    "direction","confidence","funding","open_interest","oi_delta",
    "liquidation_signal","fear_greed","regime","volatility","atr",
    "smc_score","volume_score","entry_price","stop_loss","take_profit",
)

def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    raw = d.get("extra_json") or ""
    try: d["extra_json"] = json.loads(raw) if raw else {}
    except Exception: d["extra_json"] = {}
    return d

class FeatureStore:
    def __init__(self, db_path: Optional[str] = None) -> None:
        self.db_path = db_path or get_db_path()
        logger.info(f"FeatureStore ready | db={self.db_path}")

    def _conn(self) -> ManagedConn:
        return ManagedConn(self.db_path)

    def save_row(self, features: dict, mission_id: Optional[str] = None,
                 trade_id: Optional[int] = None, symbol: str = "BTCUSDT") -> int:
        extra = {k: v for k, v in features.items() if k not in FEATURE_COLUMNS}
        with self._conn() as c:
            cur = c.execute(
                """INSERT INTO feature_rows
                   (created_at,mission_id,trade_id,symbol,direction,confidence,
                    funding,open_interest,oi_delta,liquidation_signal,fear_greed,
                    regime,volatility,atr,smc_score,volume_score,
                    entry_price,stop_loss,take_profit,extra_json)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (datetime.now(timezone.utc).isoformat(), mission_id, trade_id, symbol,
                 features.get("direction",""), float(features.get("confidence",0)),
                 float(features.get("funding",0)), float(features.get("open_interest",0)),
                 float(features.get("oi_delta",0)), float(features.get("liquidation_signal",0)),
                 float(features.get("fear_greed",50)), features.get("regime",""),
                 float(features.get("volatility",0)), float(features.get("atr",0)),
                 float(features.get("smc_score",0)), float(features.get("volume_score",0)),
                 float(features.get("entry_price",0)), float(features.get("stop_loss",0)),
                 float(features.get("take_profit",0)), json.dumps(extra) if extra else ""),
            )
            c.commit()
            return cur.lastrowid

    def update_outcome(self, row_id: int, result: Optional[float],
                        pnl: Optional[float], holding_time_s: Optional[float]) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE feature_rows SET result=?,pnl=?,holding_time_s=? WHERE id=?",
                (result, pnl, holding_time_s, row_id))
            c.commit()
            return cur.rowcount > 0

    def update_outcome_by_trade_id(self, trade_id: int, result: Optional[float],
                                    pnl: Optional[float], holding_time_s: Optional[float]) -> bool:
        with self._conn() as c:
            cur = c.execute(
                "UPDATE feature_rows SET result=?,pnl=?,holding_time_s=? WHERE trade_id=?",
                (result, pnl, holding_time_s, trade_id))
            c.commit()
            return cur.rowcount > 0

    def get_row(self, row_id: int) -> Optional[dict]:
        with self._conn() as c:
            row = c.execute("SELECT * FROM feature_rows WHERE id=?", (row_id,)).fetchone()
        return _row_to_dict(row) if row else None

    def get_recent(self, limit: int = 100, symbol: Optional[str] = None) -> List[dict]:
        with self._conn() as c:
            if symbol:
                rows = c.execute("SELECT * FROM feature_rows WHERE symbol=? ORDER BY created_at DESC LIMIT ?",
                                  (symbol, limit)).fetchall()
            else:
                rows = c.execute("SELECT * FROM feature_rows ORDER BY created_at DESC LIMIT ?",
                                  (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def get_training_rows(self, limit: int = 10_000, symbol: Optional[str] = None) -> List[dict]:
        with self._conn() as c:
            if symbol:
                rows = c.execute(
                    "SELECT * FROM feature_rows WHERE result IS NOT NULL AND symbol=? ORDER BY created_at DESC LIMIT ?",
                    (symbol, limit)).fetchall()
            else:
                rows = c.execute(
                    "SELECT * FROM feature_rows WHERE result IS NOT NULL ORDER BY created_at DESC LIMIT ?",
                    (limit,)).fetchall()
        return [_row_to_dict(r) for r in rows]

    def count(self, labelled_only: bool = False) -> int:
        with self._conn() as c:
            q = "SELECT COUNT(*) AS n FROM feature_rows" + (" WHERE result IS NOT NULL" if labelled_only else "")
            row = c.execute(q).fetchone()
        return int(row["n"]) if row else 0
