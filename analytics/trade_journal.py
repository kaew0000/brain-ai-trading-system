"""
Analytics Layer: Trade Journal
Based on: coderkhalide/Trading-Journal

All trades are persisted in SQLite.
Schema matches the specification exactly:
  timestamp · symbol · direction · regime
  bos · choch · fvg · ob · oi_delta · funding
  volume_spike · confidence · result · rr
  + extended fields for execution data

Provides
--------
TradeJournal.save_trade()
TradeJournal.update_trade_result()
TradeJournal.get_open_trades()
TradeJournal.get_daily_stats()
TradeJournal.get_consecutive_losses()
TradeJournal.get_performance_summary()
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date, timezone
from typing import List, Optional

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Trade record
# ──────────────────────────────────────────────────────────────────────────────

class TradeRecord:
    """Mirrors the journal schema; build via from_decision() or manually."""

    def __init__(self) -> None:
        self.timestamp:     str   = ""
        self.symbol:        str   = settings.SYMBOL
        self.direction:     str   = ""        # "LONG" | "SHORT"
        self.regime:        str   = ""
        self.bos:           int   = 0
        self.choch:         int   = 0
        self.fvg:           int   = 0
        self.ob:            int   = 0
        self.oi_delta:      float = 0.0
        self.funding:       float = 0.0
        self.volume_spike:  int   = 0
        self.confidence:    float = 0.0       # 0–100
        self.score:         int   = 0
        self.entry_price:   float = 0.0
        self.stop_loss:     float = 0.0
        self.take_profit:   float = 0.0
        self.quantity:      float = 0.0
        self.result:        str   = "OPEN"    # "WIN"|"LOSS"|"OPEN"|"CANCELLED"
        self.pnl:           float = 0.0
        self.rr:            float = 0.0
        self.exit_price:    float = 0.0
        self.mtf_aligned:   int   = 0
        self.block_reasons: str   = ""
        self.order_id:      str   = ""
        self.extra_data:    str   = ""

    def to_dict(self) -> dict:
        return {
            "timestamp":     self.timestamp,
            "symbol":        self.symbol,
            "direction":     self.direction,
            "regime":        self.regime,
            "bos":           self.bos,
            "choch":         self.choch,
            "fvg":           self.fvg,
            "ob":            self.ob,
            "oi_delta":      self.oi_delta,
            "funding":       self.funding,
            "volume_spike":  self.volume_spike,
            "confidence":    self.confidence,
            "score":         self.score,
            "entry_price":   self.entry_price,
            "stop_loss":     self.stop_loss,
            "take_profit":   self.take_profit,
            "quantity":      self.quantity,
            "result":        self.result,
            "pnl":           self.pnl,
            "rr":            self.rr,
            "exit_price":    self.exit_price,
            "mtf_aligned":   self.mtf_aligned,
            "block_reasons": self.block_reasons,
            "order_id":      self.order_id,
            "extra_data":    self.extra_data,
        }

    @classmethod
    def from_decision(
        cls,
        decision,           # DecisionResult or ConfidenceResult
        smc_m15,            # SMCSignals
        volume,             # VolumeSignals
        execution: Optional[dict] = None,
    ) -> "TradeRecord":
        """Build a TradeRecord from pipeline objects.

        Accepts both:
        - DecisionResult (v1): confidence is 0.0–1.0 float, score is int
        - ConfidenceResult (v2): confidence is 0–100 int, score property → raw_score
        """
        rec = cls()
        rec.timestamp     = datetime.now(timezone.utc).isoformat()
        rec.symbol        = settings.SYMBOL
        rec.direction     = decision.direction
        rec.regime        = decision.regime
        rec.bos           = 1 if smc_m15.bos    else 0
        rec.choch         = 1 if smc_m15.choch  else 0
        rec.fvg           = 1 if smc_m15.fvg    else 0
        rec.ob            = 1 if smc_m15.ob     else 0
        rec.oi_delta      = round(decision.oi_delta,     6)
        rec.funding       = round(decision.funding_rate, 6)
        rec.volume_spike  = 1 if volume.volume_spike else 0

        # Normalise confidence: ConfidenceResult stores 0-100 int,
        # DecisionResult stores 0.0-1.0 float.
        raw_conf = decision.confidence
        if isinstance(raw_conf, float) and raw_conf <= 1.0:
            rec.confidence = round(raw_conf * 100, 2)   # DecisionResult path
        else:
            rec.confidence = float(raw_conf)             # ConfidenceResult path (already 0-100)

        rec.score         = decision.score
        rec.entry_price   = decision.entry_price
        rec.stop_loss     = decision.stop_loss
        rec.take_profit   = decision.take_profit
        rec.mtf_aligned   = 1 if decision.mtf_aligned else 0
        rec.block_reasons = json.dumps(decision.block_reasons) if decision.block_reasons else ""
        rec.result        = "OPEN"

        if execution and execution.get("success"):
            rec.quantity  = execution.get("quantity", 0.0)
            entry_ord     = execution.get("entry_order")
            if entry_ord:
                rec.order_id = str(entry_ord.get("orderId", ""))

        return rec


# ──────────────────────────────────────────────────────────────────────────────
# Journal
# ──────────────────────────────────────────────────────────────────────────────

class TradeJournal:
    """
    SQLite-backed trade journal.
    Thread-safe via per-call connections.
    """

    _DDL_TRADES = """
    CREATE TABLE IF NOT EXISTS trades (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp       TEXT    NOT NULL,
        symbol          TEXT    NOT NULL,
        direction       TEXT    NOT NULL,
        regime          TEXT,
        bos             INTEGER DEFAULT 0,
        choch           INTEGER DEFAULT 0,
        fvg             INTEGER DEFAULT 0,
        ob              INTEGER DEFAULT 0,
        oi_delta        REAL    DEFAULT 0.0,
        funding         REAL    DEFAULT 0.0,
        volume_spike    INTEGER DEFAULT 0,
        confidence      REAL    DEFAULT 0.0,
        score           INTEGER DEFAULT 0,
        entry_price     REAL    DEFAULT 0.0,
        stop_loss       REAL    DEFAULT 0.0,
        take_profit     REAL    DEFAULT 0.0,
        quantity        REAL    DEFAULT 0.0,
        result          TEXT    DEFAULT 'OPEN',
        pnl             REAL    DEFAULT 0.0,
        rr              REAL    DEFAULT 0.0,
        exit_price      REAL    DEFAULT 0.0,
        mtf_aligned     INTEGER DEFAULT 0,
        block_reasons   TEXT    DEFAULT '',
        order_id        TEXT    DEFAULT '',
        extra_data      TEXT    DEFAULT ''
    );
    """

    _DDL_DAILY = """
    CREATE TABLE IF NOT EXISTS daily_stats (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        date         TEXT    NOT NULL UNIQUE,
        total_trades INTEGER DEFAULT 0,
        wins         INTEGER DEFAULT 0,
        losses       INTEGER DEFAULT 0,
        win_rate     REAL    DEFAULT 0.0,
        total_pnl    REAL    DEFAULT 0.0,
        avg_rr       REAL    DEFAULT 0.0
    );
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or settings.JOURNAL_DB_PATH
        self._init_db()
        logger.info(f"TradeJournal ready | db={self.db_path}")

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        with self._conn() as c:
            c.execute(self._DDL_TRADES)
            c.execute(self._DDL_DAILY)
            c.commit()

    # ── Write ─────────────────────────────────────────────────────────────

    def save_trade(self, rec: TradeRecord) -> int:
        sql = """
        INSERT INTO trades (
            timestamp, symbol, direction, regime,
            bos, choch, fvg, ob,
            oi_delta, funding, volume_spike,
            confidence, score,
            entry_price, stop_loss, take_profit, quantity,
            result, pnl, rr, exit_price,
            mtf_aligned, block_reasons, order_id, extra_data
        ) VALUES (
            :timestamp, :symbol, :direction, :regime,
            :bos, :choch, :fvg, :ob,
            :oi_delta, :funding, :volume_spike,
            :confidence, :score,
            :entry_price, :stop_loss, :take_profit, :quantity,
            :result, :pnl, :rr, :exit_price,
            :mtf_aligned, :block_reasons, :order_id, :extra_data
        )"""
        with self._conn() as c:
            cur = c.execute(sql, rec.to_dict())
            c.commit()
            tid = cur.lastrowid
        logger.info(f"Trade #{tid} saved | {rec.direction} result={rec.result}")
        return tid

    def update_trade_result(
        self,
        trade_id: int,
        result:     str,
        exit_price: float,
        pnl:        float,
    ) -> bool:
        """Compute RR from stored entry/SL then update the record."""
        rr = 0.0
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT entry_price, stop_loss, direction FROM trades WHERE id=?",
                    (trade_id,),
                ).fetchone()

            if row:
                entry = float(row["entry_price"])
                sl    = float(row["stop_loss"])
                risk  = abs(entry - sl)
                if risk > 0:
                    if row["direction"] == "LONG":
                        rr = (exit_price - entry) / risk
                    else:
                        rr = (entry - exit_price) / risk

            with self._conn() as c:
                c.execute(
                    "UPDATE trades SET result=?, exit_price=?, pnl=?, rr=? WHERE id=?",
                    (result, exit_price, pnl, round(rr, 3), trade_id),
                )
                c.commit()

            logger.info(f"Trade #{trade_id} → {result} pnl={pnl:.2f} rr={rr:.2f}")
            return True

        except Exception as exc:
            logger.error(f"update_trade_result error: {exc}")
            return False

    # ── Read ──────────────────────────────────────────────────────────────

    def get_open_trades(self) -> List[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades WHERE result='OPEN' ORDER BY timestamp DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def get_daily_stats(self, day: str | None = None) -> dict:
        if day is None:
            day = date.today().isoformat()
        with self._conn() as c:
            rows = c.execute(
                """SELECT result, pnl, rr FROM trades
                   WHERE date(timestamp)=? AND result NOT IN ('OPEN','CANCELLED')
                   ORDER BY timestamp""",
                (day,),
            ).fetchall()
        if not rows:
            return {"date": day, "total_trades": 0, "wins": 0, "losses": 0,
                    "win_rate": 0.0, "total_pnl": 0.0, "avg_rr": 0.0}

        total = len(rows)
        wins  = sum(1 for r in rows if r["result"] == "WIN")
        tpnl  = sum(float(r["pnl"]) for r in rows)
        arr   = sum(float(r["rr"])  for r in rows) / total
        return {
            "date":         day,
            "total_trades": total,
            "wins":         wins,
            "losses":       total - wins,
            "win_rate":     round(wins / total, 4),
            "total_pnl":    round(tpnl, 2),
            "avg_rr":       round(arr,  3),
        }

    def get_consecutive_losses(self) -> int:
        """Count unbroken loss streak from the most recent closed trade."""
        with self._conn() as c:
            rows = c.execute(
                """SELECT result FROM trades
                   WHERE result IN ('WIN','LOSS')
                   ORDER BY timestamp DESC LIMIT 20"""
            ).fetchall()
        count = 0
        for r in rows:
            if r["result"] == "LOSS":
                count += 1
            else:
                break
        return count

    def get_today_pnl(self) -> float:
        return self.get_daily_stats().get("total_pnl", 0.0)

    def get_performance_summary(self, limit: int = 200) -> dict:
        with self._conn() as c:
            rows = c.execute(
                """SELECT result, pnl, rr FROM trades
                   WHERE result IN ('WIN','LOSS')
                   ORDER BY timestamp DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        if not rows:
            return {"total_trades": 0, "message": "No closed trades yet"}

        total   = len(rows)
        wins    = sum(1 for r in rows if r["result"] == "WIN")
        tpnl    = sum(float(r["pnl"]) for r in rows)
        arr     = sum(float(r["rr"])  for r in rows) / total
        gross_p = sum(float(r["pnl"]) for r in rows if float(r["pnl"]) > 0)
        gross_l = abs(sum(float(r["pnl"]) for r in rows if float(r["pnl"]) < 0))
        pf      = round(gross_p / max(gross_l, 0.01), 3)

        return {
            "total_trades":   total,
            "wins":           wins,
            "losses":         total - wins,
            "win_rate":       round(wins / total, 4),
            "total_pnl":      round(tpnl, 2),
            "avg_rr":         round(arr,  3),
            "profit_factor":  pf,
        }
