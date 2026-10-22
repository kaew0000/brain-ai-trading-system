"""SQLite StrategyStore: local-development backend. Standard library only.

Guarantees:
* (strategy_id, version) rows are immutable - a new version is a new row.
* Every write (row + revision log entry) happens in ONE transaction; a failure rolls both back.
* WAL + busy_timeout make a crashed writer recoverable (see docs/TROUBLESHOOTING.md).
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections.abc import Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..errors import DuplicateVersionError, StorageError
from ..schemas import EvaluationResult, StrategyCategory, StrategyDefinition, ValidationStatus

log = logging.getLogger(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    category TEXT NOT NULL,
    validation_status TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (strategy_id, version)
);
CREATE TABLE IF NOT EXISTS revisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL,
    reason TEXT NOT NULL,
    detail TEXT NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS embeddings (
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    vector TEXT NOT NULL,
    PRIMARY KEY (strategy_id, version)
);
CREATE TABLE IF NOT EXISTS evaluations (
    evaluation_id TEXT PRIMARY KEY,
    strategy_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_strategy ON evaluations(strategy_id, version, created_at);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


class SQLiteStrategyStore:
    def __init__(self, path: str | Path = ":memory:") -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)  # explicit transactions
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA busy_timeout=10000")
            if self.path != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(SCHEMA)
        except sqlite3.Error as exc:
            raise StorageError(f"cannot open SQLite store at {self.path}: {exc}") from exc

    # ---- transaction helper
    @contextmanager
    def _tx(self):
        """BEGIN IMMEDIATE ... COMMIT; any exception rolls the whole transaction back and is re-raised."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield self._conn
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        else:
            self._conn.execute("COMMIT")

    @staticmethod
    def _log(conn, sid: str, ver: int, action: str, actor: str, reason: str, detail: dict[str, Any]) -> None:
        conn.execute(
            "INSERT INTO revisions(strategy_id, version, action, actor, reason, detail, at) VALUES (?,?,?,?,?,?,?)",
            (sid, ver, action, actor, reason, json.dumps(detail, default=str), _now()),
        )

    # ---- StrategyStore
    def add(self, strategy: StrategyDefinition, *, actor: str, reason: str) -> None:
        try:
            with self._tx() as c:
                c.execute(
                    "INSERT INTO strategies(strategy_id, version, category, validation_status, body, created_at) VALUES (?,?,?,?,?,?)",
                    (
                        strategy.id,
                        strategy.version,
                        strategy.category.value,
                        strategy.validation_status.value,
                        strategy.model_dump_json(),
                        strategy.created_at.isoformat(),
                    ),
                )
                self._log(
                    c,
                    strategy.id,
                    strategy.version,
                    "add",
                    actor,
                    reason,
                    {"origin": strategy.provenance.origin, "status": strategy.validation_status.value},
                )
        except sqlite3.IntegrityError as exc:
            raise DuplicateVersionError(f"{strategy.id} v{strategy.version} already exists") from exc
        except sqlite3.Error as exc:
            raise StorageError(f"add failed: {exc}") from exc

    def get(self, strategy_id: str, version: int | None = None) -> StrategyDefinition | None:
        if version is None:
            row = self._conn.execute(
                "SELECT body FROM strategies WHERE strategy_id=? ORDER BY version DESC LIMIT 1", (strategy_id,)
            ).fetchone()
        else:
            row = self._conn.execute(
                "SELECT body FROM strategies WHERE strategy_id=? AND version=?", (strategy_id, version)
            ).fetchone()
        return StrategyDefinition.model_validate_json(row["body"]) if row else None

    def list(
        self,
        *,
        category: StrategyCategory | None = None,
        status: ValidationStatus | None = None,
        latest_only: bool = True,
    ) -> list[StrategyDefinition]:
        q, args = "SELECT body, validation_status FROM strategies s", []
        where = []
        if latest_only:
            where.append("version = (SELECT MAX(version) FROM strategies WHERE strategy_id = s.strategy_id)")
        if category:
            where.append("category=?")
            args.append(category.value)
        if status:
            where.append("validation_status=?")
            args.append(status.value)
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY strategy_id, version"
        return [StrategyDefinition.model_validate_json(r["body"]) for r in self._conn.execute(q, args)]

    def history(self, strategy_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT seq, version, action, actor, reason, detail, at FROM revisions WHERE strategy_id=? ORDER BY seq",
            (strategy_id,),
        ).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]

    def set_validation(
        self,
        strategy_id: str,
        version: int,
        status: ValidationStatus,
        evidence_evaluation_id: str | None,
        approved_by: str | None,
        actor: str,
        reason: str,
    ) -> None:
        current = self.get(strategy_id, version)
        if current is None:
            raise StorageError(f"unknown strategy {strategy_id} v{version}")
        updated = current.model_copy(
            update={
                "validation_status": status,
                "evidence_evaluation_id": evidence_evaluation_id,
                "approved_by": approved_by,
            }
        )
        StrategyDefinition.model_validate(updated.model_dump())  # re-run every invariant before persisting
        try:
            with self._tx() as c:
                c.execute(
                    "UPDATE strategies SET validation_status=?, body=? WHERE strategy_id=? AND version=?",
                    (status.value, updated.model_dump_json(), strategy_id, version),
                )
                self._log(
                    c,
                    strategy_id,
                    version,
                    "set_validation",
                    actor,
                    reason,
                    {
                        "from": current.validation_status.value,
                        "to": status.value,
                        "evidence": evidence_evaluation_id,
                        "approved_by": approved_by,
                    },
                )
        except sqlite3.Error as exc:
            raise StorageError(f"set_validation failed: {exc}") from exc

    def upsert_embedding(self, strategy_id: str, version: int, vector: Sequence[float]) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO embeddings(strategy_id, version, vector) VALUES (?,?,?)",
                (strategy_id, version, json.dumps(list(vector))),
            )

    def all_embeddings(self) -> dict[tuple[str, int], list[float]]:
        return {
            (r["strategy_id"], r["version"]): json.loads(r["vector"])
            for r in self._conn.execute("SELECT strategy_id, version, vector FROM embeddings")
        }

    def save_evaluation(self, result: EvaluationResult) -> None:
        with self._tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO evaluations(evaluation_id, strategy_id, version, body, created_at) VALUES (?,?,?,?,?)",
                (
                    result.evaluation_id,
                    result.strategy_id,
                    result.strategy_version,
                    result.model_dump_json(),
                    result.created_at.isoformat(),
                ),
            )

    def latest_evaluation(self, strategy_id: str, version: int) -> EvaluationResult | None:
        row = self._conn.execute(
            "SELECT body FROM evaluations WHERE strategy_id=? AND version=? ORDER BY created_at DESC LIMIT 1",
            (strategy_id, version),
        ).fetchone()
        return EvaluationResult.model_validate_json(row["body"]) if row else None

    def get_evaluation(self, evaluation_id: str) -> EvaluationResult | None:
        row = self._conn.execute("SELECT body FROM evaluations WHERE evaluation_id=?", (evaluation_id,)).fetchone()
        return EvaluationResult.model_validate_json(row["body"]) if row else None

    def close(self) -> None:
        self._conn.close()
