"""
Journal Layer: TradeJournalV2

Extends v1 TradeJournal with the V13 unified schema (database/schema_v13.sql):
  - trades              (extended: confidence_breakdown, signal_id, explanation_id)
  - signals             (every decision cycle, traded or not)
  - market_regimes
  - market_snapshots
  - funding_history
  - oi_history
  - agent_decisions
  - agent_messages
  - ai_explanations
  - config_profiles

Design
------
TradeJournalV2 wraps TradeRecord (v1) for backward compatibility and adds
new save_* / get_* methods for the additional tables. All read methods
return plain dicts/lists ready for direct JSON serialization — this is
the data layer behind /api/signals, /api/regime, /api/trades,
/api/journal, /api/funding.

Usage
-----
journal = TradeJournalV2()
journal.save_trade(rec)                      # v1-compatible
sig_id = journal.save_signal(decision_dict)  # new
journal.save_market_regime(regime_dict, symbol="BTCUSDT")
journal.save_market_snapshot(snapshot_dict, symbol="BTCUSDT")
journal.save_funding(funding_rate, mark_price, symbol="BTCUSDT")
journal.save_oi(oi, oi_value, oi_delta_pct, symbol="BTCUSDT")
journal.save_agent_decision("SMC_ANALYST", "BOS_BULLISH", score=2, weight=0.3)
journal.save_agent_message("SMC_ANALYST", "BOS_DETECTED", "Bullish BOS detected")
journal.save_explanation(reasoning_dict, symbol="BTCUSDT", signal_id=sig_id)
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, date, timezone

from config.settings import settings
from utils.logger import get_logger
from database.db import ManagedConn, get_db_path

# Re-export v1 TradeRecord for backward compatibility
from analytics.trade_journal import TradeRecord

logger = get_logger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value) -> str:
    """Safe JSON dump — returns '' for None/empty, never raises."""
    if value is None:
        return ""
    try:
        return json.dumps(value)
    except (TypeError, ValueError):
        return json.dumps(str(value))


def _json_loads(value: str, default=None):
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _row_to_dict(row: sqlite3.Row, json_cols: tuple[str, ...] = ()) -> dict:
    """Convert a sqlite3.Row to a dict, decoding any JSON columns in-place."""
    d = dict(row)
    for col in json_cols:
        if col in d:
            d[col] = _json_loads(d[col], default={} if col != "block_reasons" else [])
    return d


# ──────────────────────────────────────────────────────────────────────────────
# Journal V2
# ──────────────────────────────────────────────────────────────────────────────

class TradeJournalV2:
    """
    SQLite-backed journal using the V13 unified schema.
    Thread-safe via per-call connections (matches v1 TradeJournal pattern).
    """

    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_db_path()
        # Trigger schema application (ManagedConn applies it on first use)
        logger.info(f"TradeJournalV2 ready | db={self.db_path}")

    def _conn(self) -> ManagedConn:
        return ManagedConn(self.db_path)

    # ════════════════════════════════════════════════════════════════════
    # TRADES  (v1-compatible + extended columns)
    # ════════════════════════════════════════════════════════════════════

    def save_trade(
        self,
        rec: TradeRecord,
        confidence_breakdown: dict | None = None,
        signal_id: int | None = None,
        explanation_id: int | None = None,
    ) -> int:
        """Insert a trade. Backward compatible with v1 TradeRecord."""
        data = rec.to_dict()
        data["confidence_breakdown"] = _json(confidence_breakdown)
        data["signal_id"] = signal_id
        data["explanation_id"] = explanation_id

        sql = """
        INSERT INTO trades (
            timestamp, symbol, direction, regime,
            bos, choch, fvg, ob,
            oi_delta, funding, volume_spike,
            confidence, confidence_breakdown, score,
            entry_price, stop_loss, take_profit, quantity,
            result, pnl, rr, exit_price,
            mtf_aligned, block_reasons, order_id,
            signal_id, explanation_id, extra_data
        ) VALUES (
            :timestamp, :symbol, :direction, :regime,
            :bos, :choch, :fvg, :ob,
            :oi_delta, :funding, :volume_spike,
            :confidence, :confidence_breakdown, :score,
            :entry_price, :stop_loss, :take_profit, :quantity,
            :result, :pnl, :rr, :exit_price,
            :mtf_aligned, :block_reasons, :order_id,
            :signal_id, :explanation_id, :extra_data
        )"""
        with self._conn() as c:
            cur = c.execute(sql, data)
            c.commit()
            tid = cur.lastrowid
        logger.info(f"Trade #{tid} saved | {rec.direction} result={rec.result}")
        return tid

    def update_trade_result(
        self,
        trade_id: int,
        result: str,
        exit_price: float,
        pnl: float,
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
                sl = float(row["stop_loss"])
                risk = abs(entry - sl)
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

    def get_open_trades(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades WHERE result='OPEN' ORDER BY timestamp DESC"
            ).fetchall()
        return [_row_to_dict(r, json_cols=("confidence_breakdown", "block_reasons")) for r in rows]

    def get_trades(self, limit: int = 100) -> list[dict]:
        """All trades, most recent first — backs /api/trades."""
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM trades ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
        return [_row_to_dict(r, json_cols=("confidence_breakdown", "block_reasons")) for r in rows]

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
        wins = sum(1 for r in rows if r["result"] == "WIN")
        tpnl = sum(float(r["pnl"]) for r in rows)
        arr = sum(float(r["rr"]) for r in rows) / total
        return {
            "date": day,
            "total_trades": total,
            "wins": wins,
            "losses": total - wins,
            "win_rate": round(wins / total, 4),
            "total_pnl": round(tpnl, 2),
            "avg_rr": round(arr, 3),
        }

    def get_consecutive_losses(self) -> int:
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

        total = len(rows)
        wins = sum(1 for r in rows if r["result"] == "WIN")
        losses = total - wins
        tpnl = sum(float(r["pnl"]) for r in rows)
        arr = sum(float(r["rr"]) for r in rows) / total
        gross_p = sum(float(r["pnl"]) for r in rows if float(r["pnl"]) > 0)
        gross_l = abs(sum(float(r["pnl"]) for r in rows if float(r["pnl"]) < 0))

        # Profit Factor: undefined when no wins (0), infinity when no losses (cap at 99)
        if gross_l == 0:
            pf = 99.0 if gross_p > 0 else 0.0
        else:
            pf = round(gross_p / gross_l, 3)

        return {
            "total_trades": total,
            "wins":         wins,
            "losses":       losses,
            "win_rate":     round(wins / total, 4),
            "total_pnl":    round(tpnl, 2),
            "avg_rr":       round(arr, 3),
            "profit_factor": pf,
        }

    # ════════════════════════════════════════════════════════════════════
    # SIGNALS — backs /api/signals and /api/decision
    # ════════════════════════════════════════════════════════════════════

    def save_signal(
        self,
        decision: dict,
        symbol: str | None = None,
        confidence_breakdown: dict | None = None,
        raw_features: dict | None = None,
    ) -> int:
        """
        Persist one decision-cycle output (DecisionResult.to_dict() or
        ConfidenceResult-derived dict). Returns the new signal id.
        """
        sql = """
        INSERT INTO signals (
            timestamp, symbol, action, direction,
            confidence, confidence_breakdown, score, max_score,
            regime, mtf_aligned, blocked, block_reasons,
            entry_price, stop_loss, take_profit, raw_features
        ) VALUES (
            :timestamp, :symbol, :action, :direction,
            :confidence, :confidence_breakdown, :score, :max_score,
            :regime, :mtf_aligned, :blocked, :block_reasons,
            :entry_price, :stop_loss, :take_profit, :raw_features
        )"""
        params = {
            "timestamp": decision.get("timestamp") or _now_iso(),
            "symbol": symbol or decision.get("symbol") or settings.SYMBOL,
            "action": decision.get("action", "SKIP"),
            "direction": decision.get("direction", ""),
            "confidence": float(decision.get("confidence", 0.0)),
            "confidence_breakdown": _json(confidence_breakdown),
            "score": int(decision.get("score", 0)),
            "max_score": int(decision.get("max_score", 9)),
            "regime": decision.get("regime", ""),
            "mtf_aligned": 1 if decision.get("mtf_aligned") else 0,
            "blocked": 1 if decision.get("blocked") else 0,
            "block_reasons": _json(decision.get("block_reasons")),
            "entry_price": float(decision.get("entry_price", 0.0)),
            "stop_loss": float(decision.get("stop_loss", 0.0)),
            "take_profit": float(decision.get("take_profit", 0.0)),
            "raw_features": _json(raw_features),
        }
        with self._conn() as c:
            cur = c.execute(sql, params)
            c.commit()
            sid = cur.lastrowid
        logger.debug(f"Signal #{sid} saved | action={params['action']}")
        return sid

    def get_signals(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM signals"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [
            _row_to_dict(r, json_cols=("confidence_breakdown", "block_reasons", "raw_features"))
            for r in rows
        ]

    def get_latest_signal(self, symbol: str | None = None) -> dict | None:
        rows = self.get_signals(limit=1, symbol=symbol)
        return rows[0] if rows else None

    # ════════════════════════════════════════════════════════════════════
    # MARKET REGIMES — backs /api/regime
    # ════════════════════════════════════════════════════════════════════

    def save_market_regime(self, regime: dict, symbol: str | None = None) -> int:
        sql = """
        INSERT INTO market_regimes (
            timestamp, symbol, regime, confidence, adx, bb_width,
            atr_normalized, probabilities
        ) VALUES (
            :timestamp, :symbol, :regime, :confidence, :adx, :bb_width,
            :atr_normalized, :probabilities
        )"""
        params = {
            "timestamp": _now_iso(),
            "symbol": symbol or settings.SYMBOL,
            "regime": regime.get("regime", ""),
            "confidence": float(regime.get("confidence", 0.0)),
            "adx": float(regime.get("adx", 0.0)),
            "bb_width": float(regime.get("bb_width", 0.0)),
            "atr_normalized": float(regime.get("atr_normalized", 0.0)),
            "probabilities": _json(regime.get("probabilities")),
        }
        with self._conn() as c:
            cur = c.execute(sql, params)
            c.commit()
            return cur.lastrowid

    def get_market_regimes(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM market_regimes"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("probabilities",)) for r in rows]

    def get_latest_regime(self, symbol: str | None = None) -> dict | None:
        rows = self.get_market_regimes(limit=1, symbol=symbol)
        return rows[0] if rows else None

    # ════════════════════════════════════════════════════════════════════
    # MARKET SNAPSHOTS
    # ════════════════════════════════════════════════════════════════════

    def save_market_snapshot(self, snapshot: dict, symbol: str | None = None) -> int:
        sql = """
        INSERT INTO market_snapshots (
            timestamp, symbol, mark_price, h4_close, h1_close, m15_close,
            trend_bias_h4, trend_bias_h1, trend_bias_m15,
            ema20, ema50, ema200, vwap, adx, extra_data
        ) VALUES (
            :timestamp, :symbol, :mark_price, :h4_close, :h1_close, :m15_close,
            :trend_bias_h4, :trend_bias_h1, :trend_bias_m15,
            :ema20, :ema50, :ema200, :vwap, :adx, :extra_data
        )"""
        params = {
            "timestamp": _now_iso(),
            "symbol": symbol or settings.SYMBOL,
            "mark_price": float(snapshot.get("mark_price", 0.0)),
            "h4_close": float(snapshot.get("h4_close", 0.0)),
            "h1_close": float(snapshot.get("h1_close", 0.0)),
            "m15_close": float(snapshot.get("m15_close", 0.0)),
            "trend_bias_h4": snapshot.get("trend_bias_h4", ""),
            "trend_bias_h1": snapshot.get("trend_bias_h1", ""),
            "trend_bias_m15": snapshot.get("trend_bias_m15", ""),
            "ema20": float(snapshot.get("ema20", 0.0)),
            "ema50": float(snapshot.get("ema50", 0.0)),
            "ema200": float(snapshot.get("ema200", 0.0)),
            "vwap": float(snapshot.get("vwap", 0.0)),
            "adx": float(snapshot.get("adx", 0.0)),
            "extra_data": _json(snapshot.get("extra_data")),
        }
        with self._conn() as c:
            cur = c.execute(sql, params)
            c.commit()
            return cur.lastrowid

    def get_market_snapshots(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM market_snapshots"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("extra_data",)) for r in rows]

    # ════════════════════════════════════════════════════════════════════
    # FUNDING / OI HISTORY — backs /api/funding
    # ════════════════════════════════════════════════════════════════════

    def save_funding(self, funding_rate: float, mark_price: float = 0.0,
                      symbol: str | None = None) -> int:
        sql = """INSERT INTO funding_history (timestamp, symbol, funding_rate, mark_price)
                 VALUES (?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (_now_iso(), symbol or settings.SYMBOL,
                                   float(funding_rate), float(mark_price)))
            c.commit()
            return cur.lastrowid

    def get_funding_history(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM funding_history"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def save_oi(self, open_interest: float, oi_value: float = 0.0,
                 oi_delta_pct: float = 0.0, symbol: str | None = None) -> int:
        sql = """INSERT INTO oi_history (timestamp, symbol, open_interest, oi_value, oi_delta_pct)
                 VALUES (?, ?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (_now_iso(), symbol or settings.SYMBOL,
                                   float(open_interest), float(oi_value), float(oi_delta_pct)))
            c.commit()
            return cur.lastrowid

    def get_oi_history(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM oi_history"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    # ════════════════════════════════════════════════════════════════════
    # AGENT DECISIONS / MESSAGES — Pixel Office feed
    # ════════════════════════════════════════════════════════════════════

    def save_agent_decision(
        self,
        agent: str,
        decision: str,
        symbol: str | None = None,
        score: float = 0.0,
        weight: float = 0.0,
        details: dict | None = None,
        signal_id: int | None = None,
    ) -> int:
        sql = """
        INSERT INTO agent_decisions (timestamp, agent, symbol, decision, score, weight, details, signal_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (
                _now_iso(), agent, symbol or settings.SYMBOL, decision,
                float(score), float(weight), _json(details), signal_id,
            ))
            c.commit()
            return cur.lastrowid

    def get_agent_decisions(self, limit: int = 100, agent: str | None = None) -> list[dict]:
        sql = "SELECT * FROM agent_decisions"
        args: tuple = ()
        if agent:
            sql += " WHERE agent=?"
            args = (agent,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("details",)) for r in rows]

    def get_agent_performance(self, limit: int = 500) -> list[dict]:
        """
        Per-agent win-rate — Phase 4B Step 1 (architecture.md §27).

        Joins agent_decisions back to trades via the signal_id both tables
        already carried in the V13 schema (agent_decisions.signal_id,
        trades.signal_id) — no new tables or columns. Only counts a vote
        toward its agent's record when ad.decision matches the direction
        that was actually traded (t.direction): a dissenting agent didn't
        get the trade it voted for, so it is neither credited with the win
        nor blamed for the loss.

        Returns one row per agent with raw win/loss counts and total_pnl —
        deliberately NOT a weight recommendation. A future phase (4B proper)
        decides how/when to trust this (e.g. a minimum-sample-size floor
        before letting it influence CEOAgent.WEIGHTS) — this method only
        answers "what actually happened per agent so far".
        """
        sql = """
        SELECT ad.agent AS agent,
               COUNT(*) AS total,
               SUM(CASE WHEN t.result = 'WIN'  THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN t.result = 'LOSS' THEN 1 ELSE 0 END) AS losses,
               SUM(t.pnl) AS total_pnl
        FROM agent_decisions ad
        JOIN trades t ON t.signal_id = ad.signal_id
        WHERE t.result IN ('WIN', 'LOSS')
          AND ad.signal_id IS NOT NULL
          AND ad.decision = t.direction
        GROUP BY ad.agent
        ORDER BY wins DESC
        LIMIT ?
        """
        with self._conn() as c:
            rows = c.execute(sql, (limit,)).fetchall()

        out = []
        for r in rows:
            total = r["total"] or 0
            wins  = r["wins"] or 0
            out.append({
                "agent":        r["agent"],
                "total_trades": total,
                "wins":         wins,
                "losses":       r["losses"] or 0,
                "win_rate":     round(wins / total, 4) if total else 0.0,
                "total_pnl":    round(float(r["total_pnl"] or 0.0), 2),
            })
        return out

    def save_agent_message(
        self,
        agent: str,
        event: str,
        message: str,
        severity: str = "info",
        payload: dict | None = None,
    ) -> int:
        sql = """
        INSERT INTO agent_messages (timestamp, agent, event, message, severity, payload)
        VALUES (?, ?, ?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (_now_iso(), agent, event, message, severity, _json(payload)))
            c.commit()
            return cur.lastrowid

    def get_agent_messages(self, limit: int = 100, agent: str | None = None) -> list[dict]:
        sql = "SELECT * FROM agent_messages"
        args: tuple = ()
        if agent:
            sql += " WHERE agent=?"
            args = (agent,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("payload",)) for r in rows]

    # ════════════════════════════════════════════════════════════════════
    # AI EXPLANATIONS — backs /api/journal (causal reasoning)
    # ════════════════════════════════════════════════════════════════════

    def save_explanation(
        self,
        reasoning: dict,
        symbol: str | None = None,
        signal_id: int | None = None,
        direction: str = "",
        confidence: float = 0.0,
        summary: str = "",
    ) -> int:
        sql = """
        INSERT INTO ai_explanations (timestamp, symbol, signal_id, direction, confidence, summary, reasoning)
        VALUES (?, ?, ?, ?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (
                _now_iso(), symbol or settings.SYMBOL, signal_id, direction,
                float(confidence), summary, _json(reasoning),
            ))
            c.commit()
            return cur.lastrowid

    def get_explanations(self, limit: int = 100, symbol: str | None = None) -> list[dict]:
        sql = "SELECT * FROM ai_explanations"
        args: tuple = ()
        if symbol:
            sql += " WHERE symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("reasoning",)) for r in rows]

    def get_latest_explanation(self, symbol: str | None = None) -> dict | None:
        rows = self.get_explanations(limit=1, symbol=symbol)
        return rows[0] if rows else None

    # ════════════════════════════════════════════════════════════════════
    # CONFIG PROFILES
    # ════════════════════════════════════════════════════════════════════

    def save_config_profile(self, name: str, config: dict, active: bool = False) -> int:
        now = _now_iso()
        with self._conn() as c:
            existing = c.execute(
                "SELECT id FROM config_profiles WHERE name=?", (name,)
            ).fetchone()
            if active:
                c.execute("UPDATE config_profiles SET active=0")
            if existing:
                c.execute(
                    "UPDATE config_profiles SET config_json=?, active=?, updated_at=? WHERE name=?",
                    (_json(config), 1 if active else 0, now, name),
                )
                pid = existing["id"]
            else:
                cur = c.execute(
                    """INSERT INTO config_profiles (name, active, created_at, updated_at, config_json)
                       VALUES (?, ?, ?, ?, ?)""",
                    (name, 1 if active else 0, now, now, _json(config)),
                )
                pid = cur.lastrowid
            c.commit()
        return pid

    def get_config_profile(self, name: str) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM config_profiles WHERE name=?", (name,)
            ).fetchone()
        if not row:
            return None
        return _row_to_dict(row, json_cols=("config_json",))

    def get_active_config_profile(self) -> dict | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM config_profiles WHERE active=1 LIMIT 1"
            ).fetchone()
        if not row:
            return None
        return _row_to_dict(row, json_cols=("config_json",))

    def list_config_profiles(self) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM config_profiles ORDER BY name"
            ).fetchall()
        return [_row_to_dict(r, json_cols=("config_json",)) for r in rows]
