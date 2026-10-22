"""Idempotent, transactional recorder of completed trades (SQLite, standard library only).

Rules:
* only CLOSED trades with every outcome field present are accepted; OPEN/CANCELLED/incomplete are REJECTED;
* the same trade_id is never processed twice (identical payload -> 'duplicate'; different payload -> 'conflict',
  and the stored row is NOT overwritten);
* outcome-based evaluation reads only rows with verified=1.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import StorageError
from ..schemas import TradeRecord

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trade_outcomes (
    trade_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    strategy_version INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    regime TEXT,
    direction TEXT NOT NULL,
    exit_time TEXT NOT NULL,
    net_pnl REAL NOT NULL,
    verified INTEGER NOT NULL,
    payload TEXT NOT NULL,
    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_outcomes_strategy ON trade_outcomes(strategy_id, strategy_version, exit_time);
"""

REQUIRED_WHEN_CLOSED = (
    "entry_time",
    "exit_time",
    "entry_price",
    "exit_price",
    "quantity",
    "fees",
    "funding",
    "realized_pnl",
)


@dataclass
class RecordResult:
    status: str  # recorded | duplicate | conflict | rejected
    trade_id: str
    reasons: list[str] = field(default_factory=list)


def mfe_mae(t: TradeRecord) -> tuple[float | None, float | None]:
    """Maximum favourable / adverse excursion in quote currency, when the price path extremes are known."""
    if t.entry_price is None or t.quantity is None or t.path_high is None or t.path_low is None:
        return None, None
    if t.direction.value == "LONG":
        return max(0.0, (t.path_high - t.entry_price) * t.quantity), max(0.0, (t.entry_price - t.path_low) * t.quantity)
    return max(0.0, (t.entry_price - t.path_low) * t.quantity), max(0.0, (t.path_high - t.entry_price) * t.quantity)


def net_pnl(t: TradeRecord) -> float:
    return float(t.realized_pnl or 0.0) - float(t.fees or 0.0) - float(t.funding or 0.0)


class TradeRecorder:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout=10000")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise StorageError(f"cannot open outcome store: {exc}") from exc

    @staticmethod
    def check_complete(t: TradeRecord) -> list[str]:
        problems = []
        if t.status != "CLOSED":
            problems.append(f"trade status is {t.status}; only CLOSED trades are recorded")
            return problems
        problems += [f"missing {f}" for f in REQUIRED_WHEN_CLOSED if getattr(t, f) is None]
        if t.entry_time and t.exit_time and t.exit_time < t.entry_time:
            problems.append("exit_time precedes entry_time")
        return problems

    def record(self, t: TradeRecord) -> RecordResult:
        problems = self.check_complete(t)
        if problems:
            return RecordResult("rejected", t.trade_id, problems)
        payload = t.model_dump_json()
        try:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                row = self._conn.execute(
                    "SELECT payload FROM trade_outcomes WHERE trade_id=?", (t.trade_id,)
                ).fetchone()
                if row is not None:
                    same = json.loads(row["payload"]) == json.loads(payload)
                    self._conn.execute("ROLLBACK")
                    if not same:
                        log.warning("trade %s re-submitted with DIFFERENT content; stored row kept", t.trade_id)
                    return RecordResult(
                        "duplicate" if same else "conflict",
                        t.trade_id,
                        [] if same else ["trade_id exists with different content; not overwritten"],
                    )
                self._conn.execute(
                    "INSERT INTO trade_outcomes(trade_id, strategy_id, strategy_version, symbol, regime, direction, exit_time,"
                    " net_pnl, verified, payload) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (
                        t.trade_id,
                        t.strategy_id,
                        t.strategy_version,
                        t.symbol,
                        t.regime,
                        t.direction.value,
                        t.exit_time.isoformat(),
                        net_pnl(t),
                        int(t.verified),
                        payload,
                    ),
                )
                self._conn.execute("COMMIT")
            except Exception:
                if self._conn.in_transaction:
                    self._conn.execute("ROLLBACK")
                raise
        except sqlite3.Error as exc:
            raise StorageError(f"record failed: {exc}") from exc
        return RecordResult("recorded", t.trade_id)

    def mark_verified(self, trade_id: str) -> bool:
        cur = self._conn.execute("UPDATE trade_outcomes SET verified=1 WHERE trade_id=?", (trade_id,))
        return cur.rowcount == 1

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM trade_outcomes").fetchone()[0]

    def verified_trades(self, strategy_id: str | None = None, strategy_version: int | None = None) -> list[TradeRecord]:
        q, a = "SELECT payload FROM trade_outcomes WHERE verified=1", []
        if strategy_id:
            q += " AND strategy_id=?"
            a.append(strategy_id)
        if strategy_version is not None:
            q += " AND strategy_version=?"
            a.append(strategy_version)
        q += " ORDER BY exit_time, trade_id"
        return [TradeRecord.model_validate_json(r["payload"]) for r in self._conn.execute(q, a)]

    def close(self) -> None:
        self._conn.close()
