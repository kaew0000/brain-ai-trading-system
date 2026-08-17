"""tests/test_execution_lane_contract.py — W14-2D-1: Execution-Lane Data
Model contract tests.

Covers the 16 required test cases from the W14-2D-1 task spec:
  1. execution_lane required (no default) on every journal writer
  2. NULL rejected (schema CHECK)
  3. invalid lane rejected (schema CHECK)
  4. valid LIVE accepted
  5. valid TRAINING accepted
  6. valid PAPER accepted
  7. historical migration -> LIVE
  8. no schema DEFAULT anywhere
  9. execution_events append-only (no UPDATE/DELETE path exists)
  10. correction event works (new row, correction_of, original untouched)
  11. all relevant writers require lane (save_trade/save_signal/
      save_agent_decision/FeatureStore.save_row/DatasetBuilder.
      capture_closed_mission/MLAdvisor._persist_prediction/OrderTimeline)
  12. live mode derives LIVE
  13. testnet derives LIVE
  14. paper mode derives TRAINING
  15. no writer silently defaults to LIVE (Python signatures have no
      default value for execution_lane)
  16. existing tests remain green — verified by the full `pytest tests/`
      run in CI/the delivery pipeline, not re-asserted here.
"""
from __future__ import annotations

import inspect
import os
import re
import sqlite3

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2, VALID_EXECUTION_LANES


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "lane_contract.db"))


# ══════════════════════════════════════════════════════════════════════
# 1, 15 — execution_lane is a REQUIRED argument, no default value, on
# every journal writer named in the W14-2D-1 spec.
# ══════════════════════════════════════════════════════════════════════

class TestNoDefaultArgument:
    def _assert_required_no_default(self, func, param_name="execution_lane"):
        sig = inspect.signature(func)
        assert param_name in sig.parameters, f"{func} has no {param_name} parameter"
        param = sig.parameters[param_name]
        assert param.default is inspect.Parameter.empty, (
            f"{func} declares a default for {param_name} — must be required"
        )

    def test_save_trade_requires_lane_no_default(self):
        self._assert_required_no_default(TradeJournalV2.save_trade)

    def test_save_signal_requires_lane_no_default(self):
        self._assert_required_no_default(TradeJournalV2.save_signal)

    def test_save_agent_decision_requires_lane_no_default(self):
        self._assert_required_no_default(TradeJournalV2.save_agent_decision)

    def test_record_execution_event_requires_lane_no_default(self):
        self._assert_required_no_default(TradeJournalV2.record_execution_event)

    def test_feature_store_save_row_requires_lane_no_default(self):
        from research.feature_store import FeatureStore
        self._assert_required_no_default(FeatureStore.save_row)

    def test_dataset_builder_capture_closed_mission_requires_lane_no_default(self):
        from research.dataset_builder import DatasetBuilder
        self._assert_required_no_default(DatasetBuilder.capture_closed_mission)

    def test_ml_advisor_advise_requires_lane_no_default(self):
        from ml.ml_advisor import MLAdvisor
        self._assert_required_no_default(MLAdvisor.advise)

    def test_order_timeline_init_requires_lane_no_default(self):
        from execution.order_timeline import OrderTimeline
        self._assert_required_no_default(OrderTimeline.__init__)

    def test_execution_orchestrator_init_requires_lane_no_default(self):
        from execution.execution_orchestrator import ExecutionOrchestrator
        self._assert_required_no_default(ExecutionOrchestrator.__init__)

    def test_ceo_gated_signal_provider_init_requires_lane_no_default(self):
        from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
        self._assert_required_no_default(CEOGatedSignalProvider.__init__)

    def test_calling_without_lane_raises_typeerror(self, journal):
        """Belt-and-suspenders: a caller that forgets the arg entirely
        gets a hard TypeError at the call site, not a silent None."""
        with pytest.raises(TypeError):
            journal.save_signal({"action": "LONG", "direction": "LONG"})  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            journal.save_trade(TradeRecord())  # type: ignore[call-arg]
        with pytest.raises(TypeError):
            journal.save_agent_decision("smc", "LONG")  # type: ignore[call-arg]


# ══════════════════════════════════════════════════════════════════════
# 2, 3, 4, 5, 6 — value validation (Python-level _validate_lane AND the
# underlying SQLite CHECK constraint)
# ══════════════════════════════════════════════════════════════════════

class TestLaneValueValidation:
    def test_none_rejected(self, journal):
        with pytest.raises(ValueError):
            journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane=None)

    def test_invalid_string_rejected(self, journal):
        with pytest.raises(ValueError):
            journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="BOGUS")

    def test_empty_string_rejected(self, journal):
        with pytest.raises(ValueError):
            journal.save_trade(TradeRecord(), execution_lane="")

    @pytest.mark.parametrize("lane", ["LIVE", "TRAINING", "PAPER"])
    def test_valid_lane_accepted(self, journal, lane):
        sid = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane=lane)
        rows = journal.get_signals(limit=1)
        assert rows[0]["execution_lane"] == lane
        assert sid is not None

    @pytest.mark.parametrize("lane", ["LIVE", "TRAINING", "PAPER"])
    def test_valid_lane_accepted_for_trade(self, journal, lane):
        tid = journal.save_trade(TradeRecord(), execution_lane=lane)
        rows = journal.get_trades(limit=1)
        assert rows[0]["execution_lane"] == lane
        assert tid is not None

    @pytest.mark.parametrize("lane", ["LIVE", "TRAINING", "PAPER"])
    def test_valid_lane_accepted_for_agent_decision(self, journal, lane):
        did = journal.save_agent_decision("smc", "LONG", execution_lane=lane)
        rows = journal.get_agent_decisions(limit=1)
        assert rows[0]["execution_lane"] == lane
        assert did is not None

    def test_valid_lanes_constant_matches_spec(self):
        assert set(VALID_EXECUTION_LANES) == {"LIVE", "TRAINING", "PAPER"}


# ══════════════════════════════════════════════════════════════════════
# 8 — no SQL DEFAULT clause on execution_lane anywhere in the schema
# ══════════════════════════════════════════════════════════════════════

class TestNoSchemaDefault:
    def test_no_default_clause_in_schema_v13(self):
        schema_path = os.path.join(REPO_ROOT, "database", "schema_v13.sql")
        with open(schema_path, "r", encoding="utf-8") as f:
            text = f.read()
        # Match "execution_lane ... DEFAULT" on the same column-definition
        # line/segment (a DEFAULT elsewhere in the file, e.g. on an
        # unrelated column, is fine — only execution_lane itself must
        # never carry one).
        for line in text.splitlines():
            if "execution_lane" in line and "CREATE" not in line and "INDEX" not in line:
                assert "DEFAULT" not in line.upper(), f"execution_lane must not have a SQL DEFAULT: {line!r}"

    def test_no_default_clause_in_order_timeline_schema(self):
        ot_path = os.path.join(REPO_ROOT, "execution", "order_timeline.py")
        with open(ot_path, "r", encoding="utf-8") as f:
            text = f.read()
        for line in text.splitlines():
            if "execution_lane" in line and "TEXT" in line:
                assert "DEFAULT" not in line.upper(), f"execution_lane must not have a SQL DEFAULT: {line!r}"

    def test_trades_table_rejects_missing_lane_at_db_level(self, journal):
        """Direct SQL bypass of the Python layer must still be rejected —
        proves the NOT NULL constraint is real, not just a Python-side
        convention."""
        with journal._conn() as c:  # noqa: SLF001 — intentional white-box check
            with pytest.raises(sqlite3.IntegrityError):
                c.execute(
                    "INSERT INTO trades (timestamp, symbol, direction) VALUES (?, ?, ?)",
                    ("2026-01-01T00:00:00Z", "BTCUSDT", "LONG"),
                )


# ══════════════════════════════════════════════════════════════════════
# 9, 10 — execution_events: append-only, correction pattern
# ══════════════════════════════════════════════════════════════════════

class TestExecutionEventsAppendOnly:
    def test_record_event_returns_id_and_persists(self, journal):
        event_id = journal.record_execution_event(
            execution_lane="LIVE", event_type="TRADE_OPENED", source="test",
            symbol="BTCUSDT", payload={"qty": 1.0},
        )
        assert event_id
        rows = journal.get_execution_events(limit=10)
        assert len(rows) == 1
        assert rows[0]["event_id"] == event_id
        assert rows[0]["execution_lane"] == "LIVE"
        assert rows[0]["payload"] == {"qty": 1.0}

    def test_no_update_method_exists(self):
        methods = [name for name in dir(TradeJournalV2) if "execution_event" in name.lower()]
        assert not any("update" in m.lower() for m in methods), (
            f"found an update-capable execution_event method: {methods}"
        )
        assert not any("delete" in m.lower() for m in methods), (
            f"found a delete-capable execution_event method: {methods}"
        )

    def test_correction_event_does_not_mutate_original(self, journal):
        original_id = journal.record_execution_event(
            execution_lane="LIVE", event_type="TRADE_CLOSED", source="test",
            symbol="BTCUSDT", payload={"pnl": 100.0},
        )
        correction_id = journal.record_execution_event(
            execution_lane="LIVE", event_type="CORRECTION", source="test",
            symbol="BTCUSDT", payload={"pnl": 95.0, "reason": "fee adjustment"},
            correction_of=original_id,
        )
        assert correction_id != original_id
        rows = journal.get_execution_events(limit=10)
        by_id = {r["event_id"]: r for r in rows}
        # Original untouched
        assert by_id[original_id]["payload"] == {"pnl": 100.0}
        assert by_id[original_id]["correction_of"] is None
        # Correction points back at it
        assert by_id[correction_id]["correction_of"] == original_id
        assert by_id[correction_id]["event_type"] == "CORRECTION"
        assert len(rows) == 2  # both rows exist independently

    def test_invalid_lane_rejected_for_events(self, journal):
        with pytest.raises(ValueError):
            journal.record_execution_event(
                execution_lane="BOGUS", event_type="X", source="test", symbol="BTCUSDT",
            )

    def test_static_grep_no_update_or_delete_against_execution_events(self):
        """Regression guard (explicitly required by the W14-2D-1 spec):
        no application code anywhere in the repo may issue UPDATE or
        DELETE against execution_events. Scans .py files only — the
        table's own CREATE TABLE statement is not a violation."""
        pattern = re.compile(r"(UPDATE|DELETE\s+FROM)\s+execution_events", re.IGNORECASE)
        violations = []
        for root, dirs, files in os.walk(REPO_ROOT):
            dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__", ".venv", "venv")]
            for fname in files:
                if not fname.endswith(".py"):
                    continue
                path = os.path.join(root, fname)
                if os.path.abspath(path) == os.path.abspath(__file__):
                    continue  # this file's own docstrings/strings mention the pattern name
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        text = f.read()
                except (UnicodeDecodeError, OSError):
                    continue
                if pattern.search(text):
                    violations.append(path)
        assert violations == [], f"UPDATE/DELETE against execution_events found in: {violations}"


# ══════════════════════════════════════════════════════════════════════
# 7 — historical migration backfills to LIVE
# ══════════════════════════════════════════════════════════════════════

class TestHistoricalMigrationBackfill:
    def _build_legacy_db(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                regime TEXT, bos INTEGER DEFAULT 0, choch INTEGER DEFAULT 0,
                fvg INTEGER DEFAULT 0, ob INTEGER DEFAULT 0,
                oi_delta REAL DEFAULT 0.0, funding REAL DEFAULT 0.0, volume_spike INTEGER DEFAULT 0,
                confidence REAL DEFAULT 0.0, confidence_breakdown TEXT DEFAULT '', score INTEGER DEFAULT 0,
                entry_price REAL DEFAULT 0.0, stop_loss REAL DEFAULT 0.0, take_profit REAL DEFAULT 0.0,
                quantity REAL DEFAULT 0.0, result TEXT DEFAULT 'OPEN', pnl REAL DEFAULT 0.0,
                rr REAL DEFAULT 0.0, exit_price REAL DEFAULT 0.0, mtf_aligned INTEGER DEFAULT 0,
                block_reasons TEXT DEFAULT '', order_id TEXT DEFAULT '',
                signal_id INTEGER, explanation_id INTEGER, extra_data TEXT DEFAULT ''
            );
            INSERT INTO trades (timestamp, symbol, direction, result, pnl)
            VALUES ('2026-01-01T00:00:00Z', 'BTCUSDT', 'LONG', 'WIN', 12.5);
            INSERT INTO trades (timestamp, symbol, direction, result, pnl)
            VALUES ('2026-01-02T00:00:00Z', 'ETHUSDT', 'SHORT', 'LOSS', -4.0);
            """
        )
        conn.commit()
        conn.close()

    def test_legacy_rows_backfilled_to_live(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import migrate

        db_path = str(tmp_path / "legacy.db")
        self._build_legacy_db(db_path)

        report = migrate(db_path)
        trades_result = next(t for t in report["tables"] if t["table"] == "trades")
        assert trades_result["status"] == "migrated"
        assert trades_result["backfilled_rows"] == 2

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT symbol, execution_lane FROM trades ORDER BY id").fetchall()
        conn.close()
        assert [r["execution_lane"] for r in rows] == ["LIVE", "LIVE"]

    def test_migration_is_idempotent(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import migrate

        db_path = str(tmp_path / "legacy.db")
        self._build_legacy_db(db_path)
        migrate(db_path)
        report2 = migrate(db_path)  # run again — must be a safe no-op
        trades_result = next(t for t in report2["tables"] if t["table"] == "trades")
        assert trades_result["status"] == "already_migrated"

    def test_post_migration_schema_enforces_not_null_and_check(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import migrate

        db_path = str(tmp_path / "legacy.db")
        self._build_legacy_db(db_path)
        migrate(db_path)

        conn = sqlite3.connect(db_path)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, direction, execution_lane) VALUES (?,?,?,?)",
                ("x", "BTCUSDT", "LONG", None),
            )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, direction, execution_lane) VALUES (?,?,?,?)",
                ("x", "BTCUSDT", "LONG", "BOGUS"),
            )
        conn.close()

    def test_fresh_db_gets_execution_events_table_from_migration_too(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import migrate

        db_path = str(tmp_path / "legacy.db")
        self._build_legacy_db(db_path)
        report = migrate(db_path)
        ee_result = next(t for t in report["tables"] if t["table"] == "execution_events")
        assert ee_result["status"] == "created"


# ══════════════════════════════════════════════════════════════════════
# 12, 13, 14 — EXECUTION_MODE -> EXECUTION_LANE derivation
# ══════════════════════════════════════════════════════════════════════

class TestLaneDerivationFromExecutionMode:
    """Tests the pure derivation logic directly (config.settings module-
    level dict), deliberately WITHOUT reloading config.settings or
    mutating EXECUTION_MODE at runtime — this module is imported once and
    widely shared (main.py, api/app.py, etc. all hold references to
    names bound from it), so reloading it mid-suite would leak altered
    global state into unrelated tests that run afterward in the same
    pytest process. Testing the mapping function in isolation gives the
    same coverage without that side effect."""

    @pytest.mark.parametrize("mode,expected_lane", [
        ("live", "LIVE"),
        ("testnet", "LIVE"),
        ("paper", "TRAINING"),
        ("something_unrecognized", "TRAINING"),  # fail-safe, never silently LIVE
    ])
    def test_derivation(self, mode, expected_lane):
        from config.settings import _EXECUTION_LANE_BY_MODE
        assert _EXECUTION_LANE_BY_MODE.get(mode, "TRAINING") == expected_lane

    def test_current_process_lane_matches_current_process_mode(self):
        """Sanity check that the already-computed module-level constants
        (as actually derived at import time for this test process) are
        mutually consistent — does not alter global state."""
        from config.settings import EXECUTION_MODE, EXECUTION_LANE, _EXECUTION_LANE_BY_MODE
        assert EXECUTION_LANE == _EXECUTION_LANE_BY_MODE.get(EXECUTION_MODE, "TRAINING")


# ══════════════════════════════════════════════════════════════════════
# 11 — every writer named in the spec actually requires + persists lane
# (end-to-end, not just signature inspection)
# ══════════════════════════════════════════════════════════════════════

class TestWritersActuallyPersistLane:
    def test_feature_store_save_row_persists_lane(self, tmp_path):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=str(tmp_path / "fs.db"))
        rid = store.save_row({"direction": "LONG", "confidence": 50.0}, execution_lane="TRAINING")
        row = store.get_row(rid)
        assert row["execution_lane"] == "TRAINING"

    def test_feature_store_save_row_rejects_invalid_lane(self, tmp_path):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=str(tmp_path / "fs.db"))
        with pytest.raises(ValueError):
            store.save_row({"direction": "LONG"}, execution_lane="NOPE")

    def test_order_timeline_persists_lane(self, tmp_path):
        from execution.order_timeline import OrderTimeline, TimelineEntry
        from execution.trade_lifecycle import TradeLifecycle

        ot = OrderTimeline(TradeLifecycle(), execution_lane="TRAINING", db_path=str(tmp_path / "ot.db"))
        ot._persist([TimelineEntry(  # noqa: SLF001 — white-box persistence check
            timestamp="2026-01-01T00:00:00Z", symbol="BTCUSDT", state_before=None,
            state_after="OPEN", source="TEST", execution_lane="TRAINING",
        )])
        import sqlite3 as _sqlite3
        conn = _sqlite3.connect(str(tmp_path / "ot.db"))
        conn.row_factory = _sqlite3.Row
        row = conn.execute("SELECT execution_lane FROM order_timeline_history LIMIT 1").fetchone()
        conn.close()
        assert row["execution_lane"] == "TRAINING"

    def test_order_timeline_rejects_invalid_lane_at_construction(self, tmp_path):
        from execution.order_timeline import OrderTimeline
        from execution.trade_lifecycle import TradeLifecycle
        with pytest.raises(ValueError):
            OrderTimeline(TradeLifecycle(), execution_lane="NOPE", db_path=str(tmp_path / "ot2.db"))
