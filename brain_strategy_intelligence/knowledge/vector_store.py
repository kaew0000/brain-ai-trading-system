"""Embeddings + optional PostgreSQL/pgvector backend.

IMPORTANT HONESTY NOTE: HashingEmbedder is a deterministic *lexical* hashing embedder (word uni/bi-grams hashed
into a fixed-size vector). It gives useful fuzzy keyword matching with zero dependencies and no API key, but it
is NOT a learned semantic model. Swap in a real model by implementing the `Embedder` protocol.

PgVectorStore is OPTIONAL and was NOT executed in the build environment (no PostgreSQL available) - see
docs/TESTING.md. psycopg/pgvector are imported lazily so importing this module never requires them.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Sequence
from typing import Any

from ..errors import BackendUnavailable, DuplicateVersionError, StorageError
from ..schemas import EvaluationResult, StrategyCategory, StrategyDefinition, ValidationStatus

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


class HashingEmbedder:
    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    def embed(self, text: str) -> list[float]:
        toks = tokenize(text)
        feats = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        vec = [0.0] * self.dim
        for f in feats:
            h = hashlib.blake2b(f.encode(), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "big") % self.dim
            vec[idx] += 1.0 if h[4] & 1 else -1.0
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec] if norm else vec


def cosine(a: Sequence[float], b: Sequence[float]) -> float:
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na, nb = math.sqrt(sum(x * x for x in a)), math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class PgVectorStore:
    """PostgreSQL + pgvector implementation of StrategyStore (optional, untested here)."""

    def __init__(self, dsn: str, dim: int = 256) -> None:
        try:
            import psycopg  # type: ignore[import-not-found]
        except ImportError as exc:
            raise BackendUnavailable("psycopg is not installed; run: pip install '.[postgres]'") from exc
        if not dsn:
            raise BackendUnavailable("PostgreSQL DSN environment variable is empty")
        self._psycopg = psycopg
        self.dim = dim
        try:
            self._conn = psycopg.connect(dsn, autocommit=False, connect_timeout=10)
            with self._conn, self._conn.cursor() as cur:
                cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
                cur.execute(
                    f"""CREATE TABLE IF NOT EXISTS bsi_strategies(
                    strategy_id TEXT NOT NULL, version INT NOT NULL, category TEXT NOT NULL,
                    validation_status TEXT NOT NULL, body JSONB NOT NULL, created_at TIMESTAMPTZ NOT NULL,
                    embedding vector({int(dim)}), PRIMARY KEY (strategy_id, version))"""
                )
                cur.execute("""CREATE TABLE IF NOT EXISTS bsi_revisions(
                    seq BIGSERIAL PRIMARY KEY, strategy_id TEXT, version INT, action TEXT, actor TEXT,
                    reason TEXT, detail JSONB, at TIMESTAMPTZ DEFAULT now())""")
                cur.execute("""CREATE TABLE IF NOT EXISTS bsi_evaluations(
                    evaluation_id TEXT PRIMARY KEY, strategy_id TEXT, version INT, body JSONB,
                    created_at TIMESTAMPTZ DEFAULT now())""")
        except Exception as exc:  # noqa: BLE001 - surface any driver error as a typed StorageError
            raise StorageError(f"PostgreSQL initialisation failed: {exc}") from exc

    def add(self, strategy: StrategyDefinition, *, actor: str, reason: str) -> None:
        try:
            with self._conn, self._conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO bsi_strategies(strategy_id, version, category, validation_status, body, created_at)"
                    " VALUES (%s,%s,%s,%s,%s,%s)",
                    (
                        strategy.id,
                        strategy.version,
                        strategy.category.value,
                        strategy.validation_status.value,
                        strategy.model_dump_json(),
                        strategy.created_at,
                    ),
                )
                cur.execute(
                    "INSERT INTO bsi_revisions(strategy_id, version, action, actor, reason, detail)"
                    " VALUES (%s,%s,'add',%s,%s,%s)",
                    (strategy.id, strategy.version, actor, reason, json.dumps({"origin": strategy.provenance.origin})),
                )
        except self._psycopg.errors.UniqueViolation as exc:
            raise DuplicateVersionError(f"{strategy.id} v{strategy.version} already exists") from exc
        except self._psycopg.Error as exc:
            raise StorageError(f"add failed: {exc}") from exc

    def get(self, strategy_id: str, version: int | None = None) -> StrategyDefinition | None:
        with self._conn.cursor() as cur:
            if version is None:
                cur.execute(
                    "SELECT body FROM bsi_strategies WHERE strategy_id=%s ORDER BY version DESC LIMIT 1", (strategy_id,)
                )
            else:
                cur.execute(
                    "SELECT body FROM bsi_strategies WHERE strategy_id=%s AND version=%s", (strategy_id, version)
                )
            row = cur.fetchone()
        return StrategyDefinition.model_validate(row[0]) if row else None

    def list(
        self,
        *,
        category: StrategyCategory | None = None,
        status: ValidationStatus | None = None,
        latest_only: bool = True,
    ) -> list[StrategyDefinition]:
        q = "SELECT body FROM bsi_strategies s WHERE TRUE"
        args: list[Any] = []
        if latest_only:
            q += " AND version=(SELECT MAX(version) FROM bsi_strategies WHERE strategy_id=s.strategy_id)"
        if category:
            q += " AND category=%s"
            args.append(category.value)
        if status:
            q += " AND validation_status=%s"
            args.append(status.value)
        with self._conn.cursor() as cur:
            cur.execute(q + " ORDER BY strategy_id, version", args)
            return [StrategyDefinition.model_validate(r[0]) for r in cur.fetchall()]

    def history(self, strategy_id: str) -> list[dict[str, Any]]:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT seq, version, action, actor, reason, detail, at FROM bsi_revisions"
                " WHERE strategy_id=%s ORDER BY seq",
                (strategy_id,),
            )
            return [
                dict(zip(("seq", "version", "action", "actor", "reason", "detail", "at"), r, strict=True))
                for r in cur.fetchall()
            ]

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
        StrategyDefinition.model_validate(updated.model_dump())
        with self._conn, self._conn.cursor() as cur:
            cur.execute(
                "UPDATE bsi_strategies SET validation_status=%s, body=%s WHERE strategy_id=%s AND version=%s",
                (status.value, updated.model_dump_json(), strategy_id, version),
            )
            cur.execute(
                "INSERT INTO bsi_revisions(strategy_id, version, action, actor, reason, detail)"
                " VALUES (%s,%s,'set_validation',%s,%s,%s)",
                (
                    strategy_id,
                    version,
                    actor,
                    reason,
                    json.dumps({"to": status.value, "evidence": evidence_evaluation_id}),
                ),
            )

    def upsert_embedding(self, strategy_id: str, version: int, vector: Sequence[float]) -> None:
        with self._conn, self._conn.cursor() as cur:
            cur.execute(
                "UPDATE bsi_strategies SET embedding=%s::vector WHERE strategy_id=%s AND version=%s",
                (json.dumps(list(vector)), strategy_id, version),
            )

    def all_embeddings(self) -> dict[tuple[str, int], list[float]]:
        with self._conn.cursor() as cur:
            cur.execute("SELECT strategy_id, version, embedding::text FROM bsi_strategies WHERE embedding IS NOT NULL")
            return {(r[0], r[1]): json.loads(r[2]) for r in cur.fetchall()}

    def save_evaluation(self, result: EvaluationResult) -> None:
        with self._conn, self._conn.cursor() as cur:
            cur.execute(
                "INSERT INTO bsi_evaluations(evaluation_id, strategy_id, version, body) VALUES (%s,%s,%s,%s)"
                " ON CONFLICT (evaluation_id) DO UPDATE SET body=EXCLUDED.body",
                (result.evaluation_id, result.strategy_id, result.strategy_version, result.model_dump_json()),
            )

    def latest_evaluation(self, strategy_id: str, version: int) -> EvaluationResult | None:
        with self._conn.cursor() as cur:
            cur.execute(
                "SELECT body FROM bsi_evaluations WHERE strategy_id=%s AND version=%s ORDER BY created_at DESC LIMIT 1",
                (strategy_id, version),
            )
            row = cur.fetchone()
        return EvaluationResult.model_validate(row[0]) if row else None

    def close(self) -> None:
        self._conn.close()
