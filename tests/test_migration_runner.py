"""tests/test_migration_runner.py — V16 Phase 4C: Automatic Migration
Runner contract tests.

Scope: this file tests database/migrations/runner.py's own logic
(registry iteration, idempotency across repeated calls, default
db_path resolution, failure propagation). It deliberately does NOT
re-test migration_001_execution_lane_backfill's internal correctness
(rebuild-with-backfill, CHECK/NOT NULL enforcement, per-table status
values) — that is already covered by
tests/test_execution_lane_contract.py::TestHistoricalMigrationBackfill.
Duplicating those assertions here would just be two tests guarding the
same behavior.
"""
from __future__ import annotations

import sqlite3

import pytest

from database.migrations.runner import _MIGRATIONS, run_pending_migrations

pytestmark = pytest.mark.unit


def _build_legacy_db(db_path: str) -> None:
    """A pre-W14-2D-1 database file: `trades` exists but has no
    execution_lane column — exactly what an operator's real production
    file looks like if it predates that phase and was never migrated."""
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
        """
    )
    conn.commit()
    conn.close()


class TestRegistry:
    def test_registry_is_non_empty_and_well_formed(self):
        assert len(_MIGRATIONS) >= 1
        for name, fn in _MIGRATIONS:
            assert isinstance(name, str) and name
            assert callable(fn)


class TestRunPendingMigrations:
    def test_migrates_a_legacy_database(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        reports = run_pending_migrations(db_path)

        assert len(reports) == len(_MIGRATIONS)
        assert reports[0]["migration"] == "001_execution_lane_backfill"
        assert reports[0]["db_path"] == db_path

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT execution_lane FROM trades").fetchone()
        conn.close()
        assert row["execution_lane"] == "LIVE"

    def test_idempotent_across_repeated_boots(self, tmp_path):
        db_path = str(tmp_path / "legacy.db")
        _build_legacy_db(db_path)

        run_pending_migrations(db_path)          # simulates first boot on new code
        reports = run_pending_migrations(db_path)  # simulates every boot after

        trades_result = next(
            t for t in reports[0]["report"]["tables"] if t["table"] == "trades"
        )
        assert trades_result["status"] == "already_migrated"
        assert trades_result["backfilled_rows"] == 0

    def test_fresh_database_is_a_clean_noop(self, tmp_path):
        """A brand-new file (no tables yet) — _apply_schema() handles
        this case directly; the migration runner must not error out
        against a database that doesn't have the legacy tables yet."""
        db_path = str(tmp_path / "brand_new.db")
        sqlite3.connect(db_path).close()

        reports = run_pending_migrations(db_path)

        for t in reports[0]["report"]["tables"]:
            assert t["status"] in ("no_existing_table", "created")

    def test_defaults_to_database_db_get_db_path(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "default_path.db")
        sqlite3.connect(db_path).close()
        monkeypatch.setattr(
            "database.migrations.runner.get_db_path", lambda: db_path
        )

        reports = run_pending_migrations()  # no db_path argument

        assert reports[0]["db_path"] == db_path

    def test_failure_is_raised_not_swallowed(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "broken.db")
        sqlite3.connect(db_path).close()

        def _boom(_db_path: str) -> dict:
            raise RuntimeError("simulated migration failure")

        monkeypatch.setattr(
            "database.migrations.runner._MIGRATIONS", [("broken_migration", _boom)]
        )

        with pytest.raises(RuntimeError, match="simulated migration failure"):
            run_pending_migrations(db_path)

    def test_stops_at_first_failure_does_not_run_later_migrations(self, tmp_path, monkeypatch):
        db_path = str(tmp_path / "broken.db")
        sqlite3.connect(db_path).close()
        calls: list[str] = []

        def _boom(_db_path: str) -> dict:
            calls.append("boom")
            raise RuntimeError("first migration fails")

        def _should_not_run(_db_path: str) -> dict:
            calls.append("should_not_run")
            return {"tables": []}

        monkeypatch.setattr(
            "database.migrations.runner._MIGRATIONS",
            [("boom", _boom), ("later", _should_not_run)],
        )

        with pytest.raises(RuntimeError):
            run_pending_migrations(db_path)

        assert calls == ["boom"]
