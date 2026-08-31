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

# ── W14-2D-1: execution_lane contract ─────────────────────────────────────
# Single validation point for every journal writer below. Deliberately
# raises rather than coercing — see docs/architecture.md's W14-2D-1 section:
# "no implicit/default lane that can make a TRAINING event look like LIVE".
VALID_EXECUTION_LANES = ("LIVE", "TRAINING", "PAPER")


def _validate_lane(execution_lane: str) -> str:
    if execution_lane not in VALID_EXECUTION_LANES:
        raise ValueError(
            f"execution_lane must be one of {VALID_EXECUTION_LANES}, got {execution_lane!r}"
        )
    return execution_lane


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
        execution_lane: str,
        confidence_breakdown: dict | None = None,
        signal_id: int | None = None,
        explanation_id: int | None = None,
    ) -> int:
        """Insert a trade. Backward compatible with v1 TradeRecord.

        W14-2D-1: execution_lane is REQUIRED with no default — see
        docs/architecture.md's W14-2D-1 section. This is the authoritative
        lane for the row regardless of whether `rec.execution_lane` was
        also set by the caller; passing a mismatched value here is a bug
        in the caller, not something this method silently reconciles.
        """
        data = rec.to_dict()
        data["confidence_breakdown"] = _json(confidence_breakdown)
        data["signal_id"] = signal_id
        data["explanation_id"] = explanation_id
        data["execution_lane"] = _validate_lane(execution_lane)

        sql = """
        INSERT INTO trades (
            timestamp, symbol, direction, regime,
            bos, choch, fvg, ob,
            oi_delta, funding, volume_spike,
            confidence, confidence_breakdown, score,
            entry_price, stop_loss, take_profit, quantity,
            result, pnl, rr, exit_price,
            mtf_aligned, block_reasons, order_id,
            signal_id, explanation_id, extra_data, execution_lane
        ) VALUES (
            :timestamp, :symbol, :direction, :regime,
            :bos, :choch, :fvg, :ob,
            :oi_delta, :funding, :volume_spike,
            :confidence, :confidence_breakdown, :score,
            :entry_price, :stop_loss, :take_profit, :quantity,
            :result, :pnl, :rr, :exit_price,
            :mtf_aligned, :block_reasons, :order_id,
            :signal_id, :explanation_id, :extra_data, :execution_lane
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

    def get_consecutive_losses(self, execution_lane: str | None = None) -> int:
        """Counts trailing losses in the most recent 20 closed trades.

        Bug-fix follow-up (2026-08-31): this used to query across every
        execution_lane combined. RiskEngine's LIVE-trading gate calls this
        to decide whether real capital can trade, but the always-on
        background training_lane_runner (see training_lane/
        training_lane_runner.py) writes its own PAPER/TRAINING-lane wins
        and losses into this same `trades` table -- and that lane is
        *designed* to bust and reset its small auto-training balance
        frequently. Without a lane filter, a run of ordinary training-lane
        losses could (and in production did) trip the live risk gate and
        block real trading, even with zero live trades having happened.

        execution_lane: if given, scopes the streak to just that lane
        (see VALID_EXECUTION_LANES). Defaults to None (no filter, every
        lane combined) to keep this method's existing behavior for any
        other/future caller that legitimately wants a cross-lane view --
        callers that gate real trading decisions (RiskEngine) must pass
        execution_lane="LIVE" explicitly.
        """
        sql = "SELECT result FROM trades WHERE result IN ('WIN','LOSS')"
        params: tuple = ()
        if execution_lane is not None:
            sql += " AND execution_lane=?"
            params = (_validate_lane(execution_lane),)
        sql += " ORDER BY timestamp DESC LIMIT 20"
        with self._conn() as c:
            rows = c.execute(sql, params).fetchall()
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
    # EXECUTION ATTRIBUTION — V16 Phase 4B Step 2 (architecture.md §29)
    # ════════════════════════════════════════════════════════════════════
    #
    # Execution-level facts (execution_id, order_id, fees, slippage,
    # latency_seconds) have no dedicated trades columns — trades.extra_data
    # (already part of the V13 schema, already the general-purpose "extra
    # dict" column save_trade() accepts) is reused as a namespaced JSON
    # blob instead of an ALTER TABLE migration. Per-agent participation is
    # NOT duplicated onto every trade either: trades.signal_id ->
    # agent_decisions.signal_id (the exact join get_agent_performance()
    # above already does) is the single source of truth for "which agents
    # voted on this trade" — get_trade_attribution() below reads through
    # that existing join rather than storing a second copy that could
    # drift out of sync with it.

    def save_execution_attribution(self, trade_id: int, **fields) -> bool:
        """
        Merge execution-level attribution fields into trades.extra_data
        for `trade_id` — a read-modify-write MERGE (not overwrite), so
        this can be called independently of, before, or after
        update_trade_result() without clobbering extra_data a caller
        already set. Recognised **fields (all optional — only non-None
        ones are stored): execution_id, order_id, fees, slippage,
        latency_seconds, agent_attribution (list[dict], see
        journal/trade_attribution.py's agent_attribution_from_ceo_decision()).
        Any other keyword is stored as-is too — this method doesn't
        validate field names, matching extra_data's existing free-form
        convention elsewhere in this file.

        Returns False (logged, never raises) if `trade_id` doesn't exist
        or the write fails — attribution is diagnostic data; a failure
        here must never be allowed to look like the trade itself failed.
        """
        payload = {k: v for k, v in fields.items() if v is not None}
        if not payload:
            return True  # nothing to merge is not an error
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT extra_data FROM trades WHERE id=?", (trade_id,)
                ).fetchone()
                if row is None:
                    logger.warning(f"save_execution_attribution: no trade #{trade_id}")
                    return False
                existing = _json_loads(row["extra_data"], default={}) or {}
                attribution = existing.get("attribution", {})
                attribution.update(payload)
                existing["attribution"] = attribution
                c.execute(
                    "UPDATE trades SET extra_data=? WHERE id=?",
                    (_json(existing), trade_id),
                )
                c.commit()
            return True
        except Exception as exc:
            logger.error(f"save_execution_attribution error (trade #{trade_id}): {exc}")
            return False

    def get_trade_attribution(self, trade_id: int) -> dict | None:
        """
        Task 1 + Task 4's combined read: one trade's full attribution —
        execution facts (trades.extra_data's "attribution" key, Task 1)
        plus which agents participated and how (Task 4), joined from
        agent_decisions via the trade's signal_id exactly like
        get_agent_performance() already joins.

        Per-agent entries use this project's real CEOAgent.WEIGHTS keys
        (smc/futures/regime/risk/journal/confidence_engine) — see
        journal/trade_attribution.py's module docstring for why. If the
        trade carries an explicit agent_attribution (a caller passed one
        to save_execution_attribution() / record_trade_outcome()
        directly), that is returned as-is instead of the join — the
        explicit value is assumed more complete. Returns an EMPTY
        agent_participation list (never fabricated entries) for any
        trade whose signal_id has no agent_decisions rows — today that
        is every trade taken through the V16 multi-symbol path, since
        execution/portfolio_signal_provider.py's pipeline doesn't run
        the agent layer (see docs/architecture.md §29 "Scope boundary" —
        an honest, pre-existing gap, not a bug in this method).
        """
        with self._conn() as c:
            trade = c.execute("SELECT * FROM trades WHERE id=?", (trade_id,)).fetchone()
            if trade is None:
                return None
            trade_d = _row_to_dict(trade, json_cols=("confidence_breakdown", "block_reasons", "extra_data"))

            agents: list[dict] = []
            if trade["signal_id"] is not None:
                rows = c.execute(
                    "SELECT * FROM agent_decisions WHERE signal_id=? ORDER BY id",
                    (trade["signal_id"],),
                ).fetchall()
                agents = [_row_to_dict(r, json_cols=("details",)) for r in rows]

        attribution = trade_d.get("extra_data") or {}
        attribution = attribution.get("attribution", {}) if isinstance(attribution, dict) else {}

        agent_participation = attribution.get("agent_attribution") or [
            {
                "agent":        a["agent"],
                "vote":         a["decision"],
                "weight":       a["weight"],
                "confidence":   a["score"],
                "contribution": round(a["score"] * a["weight"], 2),
            }
            for a in agents
        ]

        return {
            "trade_id":            trade_d["id"],
            "symbol":              trade_d["symbol"],
            "timestamp":           trade_d["timestamp"],
            "direction":           trade_d["direction"],
            "entry_price":         trade_d["entry_price"],
            "exit_price":          trade_d["exit_price"],
            "result":              trade_d["result"],
            "pnl":                 trade_d["pnl"],
            "order_id":            trade_d["order_id"] or attribution.get("order_id"),
            "execution_id":        attribution.get("execution_id"),
            "fees":                attribution.get("fees"),
            "slippage":            attribution.get("slippage"),
            "latency_seconds":     attribution.get("latency_seconds"),
            "agent_participation": agent_participation,
            # V16 Phase 4C Step 1: purely additive — every key below
            # surfaces data that was already being written (trades
            # columns since §2A; reason/source/duration_seconds/
            # confidence since §32/Phase 4B Step 3D's record_trade_outcome()
            # extension) but that this method wasn't yet returning.
            # Nothing above this comment changed name, type, or value.
            "quantity":            trade_d.get("quantity"),
            "stop_loss":           trade_d.get("stop_loss"),
            "take_profit":         trade_d.get("take_profit"),
            "rr":                  trade_d.get("rr"),
            "regime":              trade_d.get("regime") or None,
            "signal_confidence":   trade_d.get("confidence") or None,  # confidence at signal/open time (trades.confidence)
            "score":               trade_d.get("score"),
            "mtf_aligned":         trade_d.get("mtf_aligned"),
            "smc_flags": {
                "bos":   trade_d.get("bos"),
                "choch": trade_d.get("choch"),
                "fvg":   trade_d.get("fvg"),
                "ob":    trade_d.get("ob"),
            },
            "reason":              attribution.get("reason"),        # e.g. a execution.trade_lifecycle.CloseSource value
            "source":              attribution.get("source"),
            "duration_seconds":    attribution.get("duration_seconds"),
            "close_confidence":    attribution.get("confidence"),    # confidence recorded at CLOSE time (distinct from signal_confidence above)
        }

    def get_ensemble_learning_dataset(self, limit: int = 1000, symbol: str | None = None) -> list[dict]:
        """
        Task 6/7 (architecture.md §29): one clean, flat row per CLOSED
        trade — trade facts + execution attribution + per-agent
        participation — ready for a future Phase 4C to consume. This
        method only reads and shapes EXISTING data (trades,
        agent_decisions, extra_data); it computes no weights and makes
        no learning decisions — see journal/trade_attribution.py's
        module docstring for why that's deliberately out of scope here.

        Deliberately reuses get_trade_attribution() per row (N+1 reads)
        rather than a second, hand-written mega-join — this is a bulk/
        offline export method (mirrors research/feature_store.py's
        get_training_rows(), also not a hot decision-cycle path), and
        reuse means the single-row and bulk-dataset shapes can never
        silently drift apart from each other.

        Rows with empty agent_participation are included, not filtered
        out — a future Phase 4C consumer needs to see that gap in the
        data (today: every V16 multi-symbol trade), not have it hidden.
        """
        sql = "SELECT id FROM trades WHERE result IN ('WIN','LOSS')"
        args: tuple = ()
        if symbol:
            sql += " AND symbol=?"
            args = (symbol,)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args = args + (limit,)
        with self._conn() as c:
            ids = [r["id"] for r in c.execute(sql, args).fetchall()]
        return [row for row in (self.get_trade_attribution(tid) for tid in ids) if row is not None]

    # ════════════════════════════════════════════════════════════════════
    # SIGNALS — backs /api/signals and /api/decision
    # ════════════════════════════════════════════════════════════════════

    def save_signal(
        self,
        decision: dict,
        execution_lane: str,
        symbol: str | None = None,
        confidence_breakdown: dict | None = None,
        raw_features: dict | None = None,
    ) -> int:
        """
        Persist one decision-cycle output (DecisionResult.to_dict() or
        ConfidenceResult-derived dict). Returns the new signal id.

        W14-2D-1: execution_lane is REQUIRED with no default — see
        docs/architecture.md's W14-2D-1 section.
        """
        sql = """
        INSERT INTO signals (
            timestamp, symbol, action, direction,
            confidence, confidence_breakdown, score, max_score,
            regime, mtf_aligned, blocked, block_reasons,
            entry_price, stop_loss, take_profit, raw_features, execution_lane
        ) VALUES (
            :timestamp, :symbol, :action, :direction,
            :confidence, :confidence_breakdown, :score, :max_score,
            :regime, :mtf_aligned, :blocked, :block_reasons,
            :entry_price, :stop_loss, :take_profit, :raw_features, :execution_lane
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
            "execution_lane": _validate_lane(execution_lane),
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
        execution_lane: str,
        symbol: str | None = None,
        score: float = 0.0,
        weight: float = 0.0,
        details: dict | None = None,
        signal_id: int | None = None,
    ) -> int:
        """W14-2D-1: execution_lane is REQUIRED with no default — see
        docs/architecture.md's W14-2D-1 section."""
        lane = _validate_lane(execution_lane)
        sql = """
        INSERT INTO agent_decisions (timestamp, agent, symbol, decision, score, weight, details, signal_id, execution_lane)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"""
        with self._conn() as c:
            cur = c.execute(sql, (
                _now_iso(), agent, symbol or settings.SYMBOL, decision,
                float(score), float(weight), _json(details), signal_id, lane,
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
        V16 Phase 4C Track A: unified across both attribution sources.

        For each closed trade, this reuses get_trade_attribution()'s
        existing agent_participation — the SAME precedence it already
        uses for the single-trade case: an explicit
        trades.extra_data.attribution.agent_attribution (W14-2A, the
        default V16 multi-symbol execution path, where signal_id is
        NULL) wins when present; otherwise it falls back to the
        agent_decisions <-> trades.signal_id join (Step 7C). A trade
        is therefore never double-counted even when both an
        agent_attribution and a signal_id with agent_decisions rows
        exist, because get_trade_attribution() only ever returns one
        or the other for a given trade, never both.

        Only counts a vote toward its agent's record when that vote's
        direction matches the direction actually traded: a dissenting
        agent didn't get the trade it voted for, so it is neither
        credited with the win nor blamed for the loss. This mirrors
        the join's original `ad.decision = t.direction` filter,
        applied here to participant["vote"] regardless of which of
        the two sources it came from.

        Returns one row per agent with raw win/loss counts and total_pnl —
        deliberately NOT a weight recommendation. A future phase (4B proper)
        decides how/when to trust this (e.g. a minimum-sample-size floor
        before letting it influence CEOAgent.WEIGHTS) — this method only
        answers "what actually happened per agent so far".
        """
        with self._conn() as c:
            closed = c.execute(
                "SELECT id FROM trades WHERE result IN ('WIN', 'LOSS') ORDER BY id"
            ).fetchall()

        stats: dict[str, dict] = {}
        for row in closed:
            attribution = self.get_trade_attribution(row["id"])
            if attribution is None:
                continue
            direction = attribution["direction"]
            result    = attribution["result"]
            pnl       = float(attribution["pnl"] or 0.0)

            for participant in attribution["agent_participation"]:
                agent = participant.get("agent")
                if agent is None or participant.get("vote") != direction:
                    continue
                bucket = stats.setdefault(
                    agent, {"total": 0, "wins": 0, "losses": 0, "total_pnl": 0.0}
                )
                bucket["total"] += 1
                if result == "WIN":
                    bucket["wins"] += 1
                elif result == "LOSS":
                    bucket["losses"] += 1
                bucket["total_pnl"] += pnl

        out = [
            {
                "agent":        agent,
                "total_trades": b["total"],
                "wins":         b["wins"],
                "losses":       b["losses"],
                "win_rate":     round(b["wins"] / b["total"], 4) if b["total"] else 0.0,
                "total_pnl":    round(b["total_pnl"], 2),
            }
            for agent, b in stats.items()
        ]
        out.sort(key=lambda r: r["wins"], reverse=True)
        return out[:limit]

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
    # EXECUTION EVENTS — W14-2D-1: immutable, append-only audit trail
    # ════════════════════════════════════════════════════════════════════
    #
    # See database/schema_v13.sql's execution_events table comment for the
    # full contract. This is the ONLY method in this module allowed to
    # write to execution_events, and it is INSERT-only by construction —
    # there is no update_execution_event()/delete_execution_event() method
    # anywhere in this class, deliberately. A correction is recorded as a
    # brand-new row via correction_of, never by mutating the original.
    # tests/test_execution_lane_contract.py statically greps this whole
    # repository for the SQL verbs that would mutate this table, paired
    # with this table's name, and fails the suite if either appears.

    def record_execution_event(
        self,
        execution_lane: str,
        event_type: str,
        source: str,
        symbol: str,
        payload: dict | None = None,
        order_id: str | None = None,
        trade_id: int | None = None,
        correction_of: str | None = None,
    ) -> str:
        """Append one immutable event. Returns the new event_id (uuid4).

        W14-2D-1: execution_lane is REQUIRED with no default. A
        correction is created by calling this again with
        event_type="CORRECTION" and correction_of=<original event_id> —
        never by editing the original row.
        """
        import uuid

        lane = _validate_lane(execution_lane)
        event_id = str(uuid.uuid4())
        sql = """
        INSERT INTO execution_events (
            event_id, execution_lane, timestamp, symbol, order_id, trade_id,
            event_type, source, payload, schema_version, correction_of
        ) VALUES (
            :event_id, :execution_lane, :timestamp, :symbol, :order_id, :trade_id,
            :event_type, :source, :payload, :schema_version, :correction_of
        )"""
        params = {
            "event_id": event_id,
            "execution_lane": lane,
            "timestamp": _now_iso(),
            "symbol": symbol,
            "order_id": order_id,
            "trade_id": trade_id,
            "event_type": event_type,
            "source": source,
            "payload": _json(payload or {}),
            "schema_version": 1,
            "correction_of": correction_of,
        }
        with self._conn() as c:
            c.execute(sql, params)
            c.commit()
        logger.info(f"ExecutionEvent #{event_id} saved | lane={lane} type={event_type}")
        return event_id

    def get_execution_events(
        self,
        limit: int = 100,
        execution_lane: str | None = None,
        symbol: str | None = None,
        trade_id: int | None = None,
    ) -> list[dict]:
        """Read-only. No filtering-by-default — an explicit execution_lane
        must be passed to scope results to one lane; omitting it returns
        events across all lanes (read path only, not a writer contract)."""
        sql = "SELECT * FROM execution_events WHERE 1=1"
        args: list = []
        if execution_lane is not None:
            sql += " AND execution_lane=?"
            args.append(_validate_lane(execution_lane))
        if symbol is not None:
            sql += " AND symbol=?"
            args.append(symbol)
        if trade_id is not None:
            sql += " AND trade_id=?"
            args.append(trade_id)
        sql += " ORDER BY timestamp DESC LIMIT ?"
        args.append(limit)
        with self._conn() as c:
            rows = c.execute(sql, args).fetchall()
        return [_row_to_dict(r, json_cols=("payload",)) for r in rows]

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
