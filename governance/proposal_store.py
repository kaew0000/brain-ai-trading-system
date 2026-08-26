"""governance/proposal_store.py — persistence for UpdateProposal rows.

Same shape as ml/model_registry.py's ModelRegistry on purpose: a thin class
wrapping database.db.ManagedConn, a module-level singleton via
get_proposal_store()/reset_proposal_store() (the latter for tests — same
reset_model_registry(db_path=...) pattern already established), no ORM.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone

from database.db import ManagedConn, get_db_path
from utils.logger import get_logger

from .update_proposal import STATUSES, UpdateProposal

logger = get_logger(__name__)


class ProposalStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_db_path()
        self._lock = threading.Lock()

    def _conn(self) -> ManagedConn:
        return ManagedConn(self.db_path)

    def create(self, proposal: UpdateProposal) -> int:
        """Insert a new proposal. Always lands as status='pending' —
        callers cannot pre-approve a proposal by constructing it with a
        different status; that would defeat the entire point of this
        table (see governance/__init__.py's module docstring)."""
        proposal.status = "pending"
        row = proposal.to_row()
        cols = ", ".join(row.keys())
        placeholders = ", ".join("?" for _ in row)
        with self._conn() as c:
            cur = c.execute(
                f"INSERT INTO update_proposals ({cols}) VALUES ({placeholders})",
                tuple(row.values()),
            )
            c.commit()
            new_id = cur.lastrowid
        logger.info(
            f"ProposalStore: created #{new_id} "
            f"({proposal.proposal_type} / {proposal.target})"
        )
        return new_id

    def get(self, proposal_id: int) -> UpdateProposal | None:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM update_proposals WHERE id=?", (proposal_id,)
            ).fetchone()
        return UpdateProposal.from_row(dict(row)) if row else None

    def list(
        self,
        status: str | None = None,
        proposal_type: str | None = None,
        limit: int = 50,
    ) -> list[UpdateProposal]:
        clauses, params = [], []
        if status:
            clauses.append("status=?")
            params.append(status)
        if proposal_type:
            clauses.append("proposal_type=?")
            params.append(proposal_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._conn() as c:
            rows = c.execute(
                f"SELECT * FROM update_proposals {where} "
                f"ORDER BY id DESC LIMIT ?",
                (*params, limit),
            ).fetchall()
        return [UpdateProposal.from_row(dict(r)) for r in rows]

    def set_review(
        self,
        proposal_id: int,
        verdict: str,
        reasoning: str,
        score: float,
    ) -> bool:
        """Attach the Review Agent's opinion. Does NOT touch `status` —
        the review is advisory input for a human, never a decision by
        itself (see agents/update_review_agent.py's module docstring)."""
        with self._lock, self._conn() as c:
            cur = c.execute(
                """UPDATE update_proposals
                   SET review_verdict=?, review_reasoning=?, review_score=?,
                       updated_at=?
                   WHERE id=?""",
                (verdict, reasoning, float(score), _now_iso(), proposal_id),
            )
            c.commit()
            changed = cur.rowcount > 0
        if changed:
            logger.info(f"ProposalStore: reviewed #{proposal_id} -> {verdict} ({score:.2f})")
        return changed

    def set_status(self, proposal_id: int, status: str) -> bool:
        """Human decision point. `status` must be one of STATUSES (minus
        'pending', which is create()'s job only) — anything else raises
        rather than silently no-op'ing, since a typo'd status string here
        would otherwise leave a proposal permanently un-actionable."""
        if status not in STATUSES:
            raise ValueError(f"ProposalStore.set_status: unknown status {status!r}")
        now = _now_iso()
        with self._lock, self._conn() as c:
            if status in ("approved", "rejected"):
                cur = c.execute(
                    "UPDATE update_proposals SET status=?, decided_at=?, updated_at=? WHERE id=?",
                    (status, now, now, proposal_id),
                )
            elif status in ("applied", "apply_failed"):
                cur = c.execute(
                    "UPDATE update_proposals SET status=?, applied_at=?, updated_at=? WHERE id=?",
                    (status, now, now, proposal_id),
                )
            else:
                cur = c.execute(
                    "UPDATE update_proposals SET status=?, updated_at=? WHERE id=?",
                    (status, now, proposal_id),
                )
            c.commit()
            changed = cur.rowcount > 0
        if changed:
            logger.info(f"ProposalStore: #{proposal_id} -> status={status}")
        return changed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_store: ProposalStore | None = None
_store_lock = threading.Lock()


def get_proposal_store() -> ProposalStore:
    global _store
    if _store is None:
        with _store_lock:
            if _store is None:
                _store = ProposalStore()
    return _store


def reset_proposal_store(db_path: str | None = None) -> ProposalStore:
    global _store
    with _store_lock:
        _store = ProposalStore(db_path=db_path)
    return _store
