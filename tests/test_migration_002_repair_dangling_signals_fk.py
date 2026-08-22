"""Tests for database/migrations/migration_002_repair_dangling_signals_fk.py
(fix/journal-signals-fk-migration-repair, Part B).
"""
import sqlite3

import pytest

pytestmark = pytest.mark.unit


def _build_and_corrupt(db_path: str) -> None:
    """Same reproduction as tests/test_migration_001_fk_repair.py's
    TestDanglingFkDirectReproduction — duplicated in miniature here
    rather than imported, so this test file stays self-contained and
    doesn't couple to the other test module's private helpers."""
    from database.migrations.migration_001_execution_lane_backfill import (
        _extract_create_table,
        _read_schema_sql,
    )
    sql_text = _read_schema_sql()
    conn = sqlite3.connect(db_path)
    conn.executescript(_extract_create_table(sql_text, "signals"))
    conn.executescript(_extract_create_table(sql_text, "trades"))
    conn.executescript(_extract_create_table(sql_text, "ai_explanations"))
    conn.execute(
        "INSERT INTO signals (timestamp, symbol, action, execution_lane) "
        "VALUES ('2026-01-01T00:00:00Z', 'BTCUSDT', 'LONG', 'LIVE')"
    )
    conn.execute(
        "INSERT INTO trades (timestamp, symbol, direction, signal_id, execution_lane) "
        "VALUES ('2026-01-01T00:00:00Z', 'BTCUSDT', 'LONG', 1, 'LIVE')"
    )
    conn.commit()

    conn.execute("PRAGMA foreign_keys=OFF")
    for table in ("trades", "signals"):  # OLD buggy order: trades before signals
        old_cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
        cols_csv = ", ".join(old_cols)
        tmp = f"{table}_pre_w14_2d_1"
        conn.execute(f"ALTER TABLE {table} RENAME TO {tmp}")
        conn.execute(_extract_create_table(sql_text, table))
        conn.execute(f"INSERT INTO {table} ({cols_csv}) SELECT {cols_csv} FROM {tmp}")
        conn.execute(f"DROP TABLE {tmp}")
    conn.commit()
    conn.execute("PRAGMA foreign_keys=ON")
    conn.close()


class TestDryRunDefault:
    def test_dry_run_reports_but_writes_nothing(self, tmp_path):
        from database.migrations.migration_002_repair_dangling_signals_fk import repair

        db_path = str(tmp_path / "dry_run.db")
        _build_and_corrupt(db_path)

        report = repair(db_path)  # apply defaults to False

        assert report["mode"] == "dry_run"
        assert set(report["dangling_before"]) == {"trades", "ai_explanations"}
        assert report["repairs"] == []

        # Confirm nothing was actually written — the DB must still be
        # exactly as dangling as before.
        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
        )
        conn = sqlite3.connect(db_path)
        assert set(_find_dangling_fk_tables(conn)) == {"trades", "ai_explanations"}
        conn.close()

    def test_apply_false_explicit_same_as_default(self, tmp_path):
        from database.migrations.migration_002_repair_dangling_signals_fk import repair

        db_path = str(tmp_path / "dry_run_explicit.db")
        _build_and_corrupt(db_path)

        report = repair(db_path, apply=False)
        assert report["mode"] == "dry_run"
        assert report["repairs"] == []


class TestApply:
    def test_apply_actually_repairs(self, tmp_path):
        from database.migrations.migration_002_repair_dangling_signals_fk import repair

        db_path = str(tmp_path / "apply.db")
        _build_and_corrupt(db_path)

        report = repair(db_path, apply=True)

        assert report["mode"] == "apply"
        assert set(report["dangling_before"]) == {"trades", "ai_explanations"}
        assert {r["table"] for r in report["repairs"]} == {"trades", "ai_explanations"}
        assert all(r["status"] == "fk_repaired" for r in report["repairs"])

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")
        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
        )
        assert _find_dangling_fk_tables(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        # The exact operation that used to fail must now succeed.
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, signal_id, execution_lane) "
            "VALUES ('x', 'ETHUSDT', 'SHORT', 1, 'LIVE')"
        )
        conn.commit()
        conn.close()

    def test_apply_on_already_clean_db_is_a_noop(self, tmp_path):
        from database.migrations.migration_002_repair_dangling_signals_fk import repair

        db_path = str(tmp_path / "clean.db")
        _build_and_corrupt(db_path)
        repair(db_path, apply=True)  # first pass: repairs everything

        report2 = repair(db_path, apply=True)  # second pass: nothing left
        assert report2["dangling_before"] == []
        assert report2["repairs"] == []


class TestNotRegisteredInAutomaticRunner:
    def test_migration_002_is_not_in_runner_registry(self):
        """Deliberate design decision (see this module's own docstring):
        migration_002 stays manual/dry-run-gated only, unlike
        migration_001 which runs automatically every boot via
        database/migrations/runner.py. Pinned here as a static check so
        a future edit can't silently wire this into the automatic path
        without a deliberate decision to remove this test too."""
        from database.migrations.runner import _MIGRATIONS

        registered_ids = [m[0] for m in _MIGRATIONS]
        assert not any("002" in m_id for m_id in registered_ids), (
            "migration_002_repair_dangling_signals_fk should NOT be "
            "auto-registered in runner.py — it's dry-run-by-default and "
            "meant for explicit, human-confirmed invocation only, since "
            "it targets live trade history."
        )
