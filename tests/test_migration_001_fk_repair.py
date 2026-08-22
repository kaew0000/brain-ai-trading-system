"""Regression tests for fix/journal-signals-fk-migration-repair.

Root cause: database/migrations/migration_001_execution_lane_backfill.py
used to process `trades` (and `agent_decisions`) BEFORE `signals` in
_LANE_TABLES. SQLite's ALTER TABLE ... RENAME TO automatically rewrites
every OTHER table's stored foreign-key clauses that reference the
renamed table — so when `signals` was later renamed as part of its own
rebuild, the already-freshly-rebuilt `trades` table's FK silently got
rewritten to REFERENCES "signals_pre_w14_2d_1"(id), a temp table
dropped moments later. Every trade insert with a non-null signal_id
then failed with `sqlite3.OperationalError: no such table:
main.signals_pre_w14_2d_1` (411 occurrences in a real 30+-hour
production log — see PATCH_NOTES.md).

`ai_explanations` has the identical `signal_id REFERENCES signals(id)`
FK but was never in `_LANE_TABLES` at all — reordering can't touch it.
If it already existed as a table at the moment ANY migrate() call
renames `signals`, the same SQLite auto-rewrite mechanism corrupts it
too, as a side effect, regardless of table processing order.

These tests: (1) reproduce the classic bug directly against real
SQLite, independent of migrate(), to pin the repair pass's correctness
on its own; (2) confirm the current migrate() (signals-first ordering
+ unconditional repair pass) leaves `trades` clean; (3) confirm the
repair pass catches `ai_explanations`, which reordering alone cannot.
"""
import sqlite3

import pytest

pytestmark = pytest.mark.unit


# ══════════════════════════════════════════════════════════════════════
# 1 — direct reproduction + repair, independent of migrate()
# ══════════════════════════════════════════════════════════════════════

class TestDanglingFkDirectReproduction:
    def _build_already_migrated_signals_and_trades(self, db_path: str) -> None:
        """Kaew's real starting state: `signals` and `trades` already
        have `execution_lane` (added by an earlier, otherwise-successful
        run of the OLD buggy migration_001 — see
        docs/architecture.md's W14-2D-1 section) — the FK corruption is
        a separate, independent side effect of that same run, not a
        precondition that needs execution_lane to be absent. Built from
        the real schema_v13.sql text (not a hand-typed shape) so this
        fixture can't drift from what the repair pass will actually
        target."""
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
        conn.close()

    def _corrupt_trades_fk_via_old_buggy_ordering(self, db_path: str) -> None:
        """Reproduces the OLD buggy migration_001 behavior directly
        (rebuild `trades` BEFORE `signals`) against already-migrated
        tables — since the buggy ordering no longer exists anywhere in
        current source, this hand-replicates just the two ALTER TABLE
        RENAME steps whose interaction caused the corruption, using the
        real schema text for both rebuilds."""
        from database.migrations.migration_001_execution_lane_backfill import (
            _extract_create_table,
            _read_schema_sql,
        )
        sql_text = _read_schema_sql()
        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=OFF")

        for table in ("trades", "signals"):  # OLD order: trades before signals
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

    def test_old_buggy_ordering_reproduces_dangling_fk(self, tmp_path):
        """Pin the root-cause mechanism itself: rebuilding `trades`
        BEFORE `signals` (the OLD, now-reverted ordering) leaves
        `trades`'s FK dangling — and since `ai_explanations` also
        references `signals` and already exists at that point, it gets
        corrupted the exact same way, as a side effect of the very same
        `signals` rename (not because ai_explanations was itself
        rebuilt in the wrong order — it's never rebuilt by this
        migration at all)."""
        db_path = str(tmp_path / "old_ordering.db")
        self._build_already_migrated_signals_and_trades(db_path)
        self._corrupt_trades_fk_via_old_buggy_ordering(db_path)

        conn = sqlite3.connect(db_path)
        conn.execute("PRAGMA foreign_keys=ON")  # SQLite default is OFF per-connection;
        # production always enables this via database/db.py's _apply_pragmas() —
        # set explicitly here so this raw connection actually enforces it.
        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
        )
        assert set(_find_dangling_fk_tables(conn)) == {"trades", "ai_explanations"}

        with pytest.raises(sqlite3.OperationalError, match="signals_pre_w14_2d_1"):
            conn.execute(
                "INSERT INTO trades (timestamp, symbol, direction, signal_id, execution_lane) "
                "VALUES ('x', 'ETHUSDT', 'SHORT', 1, 'LIVE')"
            )
        conn.close()

    def test_repair_pass_fixes_the_reproduced_dangling_fk(self, tmp_path):
        """Same reproduction as above, then run the new repair pass
        directly and confirm it's fixed for BOTH affected tables:
        PRAGMA foreign_key_check clean, _find_dangling_fk_tables empty,
        row counts preserved, and a real insert succeeds where it
        previously failed — exactly the brief's required assertions."""
        db_path = str(tmp_path / "repair_direct.db")
        self._build_already_migrated_signals_and_trades(db_path)
        self._corrupt_trades_fk_via_old_buggy_ordering(db_path)

        conn = sqlite3.connect(db_path)
        trades_count_before = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        expl_count_before = conn.execute("SELECT COUNT(*) FROM ai_explanations").fetchone()[0]

        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
            _read_schema_sql,
            _repair_dangling_fks,
        )
        results = _repair_dangling_fks(conn, _read_schema_sql())

        assert {r["table"] for r in results} == {"trades", "ai_explanations"}
        assert all(r["status"] == "fk_repaired" for r in results)
        assert _find_dangling_fk_tables(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []

        assert conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0] == trades_count_before == 1
        assert conn.execute("SELECT COUNT(*) FROM ai_explanations").fetchone()[0] == expl_count_before == 0

        # The exact operation that used to fail must now succeed.
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, signal_id, execution_lane) "
            "VALUES ('x', 'ETHUSDT', 'SHORT', 1, 'LIVE')"
        )
        conn.commit()
        conn.close()

    def test_repair_pass_is_idempotent(self, tmp_path):
        db_path = str(tmp_path / "repair_idempotent.db")
        self._build_already_migrated_signals_and_trades(db_path)
        self._corrupt_trades_fk_via_old_buggy_ordering(db_path)

        conn = sqlite3.connect(db_path)
        from database.migrations.migration_001_execution_lane_backfill import (
            _read_schema_sql,
            _repair_dangling_fks,
        )
        sql_text = _read_schema_sql()
        first = _repair_dangling_fks(conn, sql_text)
        second = _repair_dangling_fks(conn, sql_text)

        assert {r["table"] for r in first} == {"trades", "ai_explanations"}
        assert second == []  # nothing left to repair — safe no-op
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 2 — through migrate(): signals-first ordering keeps `trades` clean
# ══════════════════════════════════════════════════════════════════════

class TestMigrateReordering:
    def _build_legacy_db(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL
            );
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                signal_id INTEGER REFERENCES signals(id)
            );
            INSERT INTO signals (timestamp, symbol, action)
            VALUES ('2026-01-01T00:00:00Z', 'BTCUSDT', 'LONG');
            """
        )
        conn.commit()
        conn.close()

    def test_migrate_leaves_trades_fk_clean(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
            migrate,
        )

        db_path = str(tmp_path / "legacy_reorder.db")
        self._build_legacy_db(db_path)
        report = migrate(db_path)

        assert report["fk_repairs"] == []  # signals-first ordering: nothing to repair

        conn = sqlite3.connect(db_path)
        assert _find_dangling_fk_tables(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute(
            "INSERT INTO trades (timestamp, symbol, direction, signal_id, execution_lane) "
            "VALUES ('x', 'BTCUSDT', 'LONG', 1, 'LIVE')"
        )
        conn.commit()
        conn.close()


# ══════════════════════════════════════════════════════════════════════
# 3 — through migrate(): ai_explanations, outside _LANE_TABLES entirely,
#     still gets caught and repaired by the generic pass
# ══════════════════════════════════════════════════════════════════════

class TestMigrateRepairsOutOfScopeTable:
    def _build_legacy_db_with_ai_explanations(self, db_path: str) -> None:
        conn = sqlite3.connect(db_path)
        conn.executescript(
            """
            CREATE TABLE signals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL, action TEXT NOT NULL
            );
            CREATE TABLE trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL, direction TEXT NOT NULL,
                signal_id INTEGER REFERENCES signals(id)
            );
            CREATE TABLE ai_explanations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL, symbol TEXT NOT NULL,
                signal_id INTEGER REFERENCES signals(id),
                reasoning TEXT NOT NULL
            );
            INSERT INTO signals (timestamp, symbol, action)
            VALUES ('2026-01-01T00:00:00Z', 'BTCUSDT', 'LONG');
            """
        )
        conn.commit()
        conn.close()

    def test_ai_explanations_fk_gets_repaired_even_though_never_rebuilt(self, tmp_path):
        """ai_explanations is not in _LANE_TABLES and migrate() never
        directly rebuilds it — but renaming `signals` (as part of
        migrate()'s own _LANE_TABLES processing) silently corrupts
        ai_explanations's FK as a side effect, same mechanism as the
        trades case, regardless of ordering. Only the generic repair
        pass — not reordering — can catch this."""
        from database.migrations.migration_001_execution_lane_backfill import (
            _find_dangling_fk_tables,
            migrate,
        )

        db_path = str(tmp_path / "legacy_ai_explanations.db")
        self._build_legacy_db_with_ai_explanations(db_path)
        report = migrate(db_path)

        repaired_tables = [r["table"] for r in report["fk_repairs"]]
        assert "ai_explanations" in repaired_tables

        conn = sqlite3.connect(db_path)
        assert _find_dangling_fk_tables(conn) == []
        assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
        conn.execute(
            "INSERT INTO ai_explanations (timestamp, symbol, signal_id, reasoning) "
            "VALUES ('x', 'BTCUSDT', 1, '{}')"
        )
        conn.commit()
        conn.close()

    def test_migrate_is_idempotent_after_fk_repair(self, tmp_path):
        from database.migrations.migration_001_execution_lane_backfill import migrate

        db_path = str(tmp_path / "legacy_idempotent.db")
        self._build_legacy_db_with_ai_explanations(db_path)
        migrate(db_path)
        report2 = migrate(db_path)  # second run — must be a safe no-op throughout
        assert report2["fk_repairs"] == []
        for t in report2["tables"]:
            assert t["status"] in ("already_migrated", "already_existed", "no_existing_table")
