"""training_lane/state_store.py — V16 Phase 4C §49: persistence for
training_lane_runner.py's restore-on-restart.

Deliberately tiny and separate from journal/journal_v2.py — a full
engine-state blob (PaperAccount + open PaperPosition(s) +
TrainingLaneRunner's own bust_count/rotation_index) is a different kind
of thing from the trade/decision journal entries TradeJournalV2 owns,
and this module owns nothing about their *shape* — it just stores and
retrieves whatever dict training_lane_runner.py hands it against the
single-row training_lane_state table (database/schema_v13.sql).

Mirrors research/feature_store.py's lightweight ManagedConn-per-call
pattern (no persistent connection held on self).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from database.db import ManagedConn, get_db_path
from utils.logger import get_logger

logger = get_logger(__name__)


class TrainingLaneStateStore:
    def __init__(self, db_path: str | None = None) -> None:
        self.db_path = db_path or get_db_path()

    def _conn(self) -> ManagedConn:
        return ManagedConn(self.db_path)

    def save_state(self, state: dict) -> None:
        """Upserts the single state row. Never raises — a failed save
        should never take down the training lane's own cycle; the
        caller logs and moves on (see TrainingLaneRunner._cycle())."""
        try:
            with self._conn() as c:
                c.execute(
                    """INSERT INTO training_lane_state (id, updated_at, state_json)
                       VALUES (1, ?, ?)
                       ON CONFLICT(id) DO UPDATE SET
                           updated_at = excluded.updated_at,
                           state_json = excluded.state_json""",
                    (datetime.now(timezone.utc).isoformat(), json.dumps(state)),
                )
                c.commit()
        except Exception as exc:
            logger.error(f"TrainingLaneStateStore.save_state failed: {exc}", exc_info=True)

    def load_state(self) -> dict | None:
        """Returns the saved state dict, or None if nothing has ever
        been saved (fresh database) or the saved row can't be parsed
        (corrupted/from an incompatible future format) — never raises;
        the caller (TrainingLaneRunner) treats None exactly the same as
        "first time this has ever run: start fresh"."""
        try:
            with self._conn() as c:
                row = c.execute(
                    "SELECT state_json FROM training_lane_state WHERE id = 1"
                ).fetchone()
            if row is None:
                return None
            return json.loads(row["state_json"])
        except Exception as exc:
            logger.error(f"TrainingLaneStateStore.load_state failed: {exc}", exc_info=True)
            return None


_store: TrainingLaneStateStore | None = None


def get_training_lane_state_store() -> TrainingLaneStateStore:
    """Module-level singleton accessor — mirrors
    research/dataset_builder.py::get_dataset_builder() /
    journal/journal_v2.py::get_trade_journal_v2()'s established pattern.
    No locking needed here (unlike those two): construction is trivial
    (no schema-touching side effect, no logged "ready" line — this is
    intentionally the lightest-weight of the three, since it's called
    from TrainingLaneRunner's own single background thread only, never
    from request-handling threads the way the journal is)."""
    global _store
    if _store is None:
        _store = TrainingLaneStateStore()
    return _store


def reset_training_lane_state_store(db_path: str | None = None) -> TrainingLaneStateStore:
    """Test-isolation hook."""
    global _store
    _store = TrainingLaneStateStore(db_path=db_path)
    return _store
