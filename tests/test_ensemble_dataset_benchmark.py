"""tests/test_ensemble_dataset_benchmark.py — V16 §77.

Covers tools/benchmark_ensemble_dataset.py: the tool that makes a regression of
get_ensemble_learning_dataset() back to an N+1 read pattern (fixed in §63)
measurable. The §63 tests (tests/test_ensemble_dataset_bulk_fetch.py) lock the
query count directly; these tests lock that the BENCHMARK itself detects the
failure modes it exists to detect, and that its healthy-baseline output is sane.

Timing assertions are deliberately loose (machine noise); the SQL-statement
count assertions are exact and hardware-independent.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from tools import benchmark_ensemble_dataset as bench
from tools.benchmark_ensemble_dataset import BenchResult

pytestmark = pytest.mark.unit


def _result(trades: int, stmts: int = 7, ms_per_trade: float = 0.05, rows: int | None = None) -> BenchResult:
    return BenchResult(trades=trades, rows=trades if rows is None else rows, ms=ms_per_trade * trades,
                       sql_statements=stmts, ms_per_trade=ms_per_trade)


class TestCheck:
    def test_healthy_curve_has_no_problems(self):
        assert bench.check([_result(100), _result(1000), _result(5000, ms_per_trade=0.06)]) == []

    def test_growing_statement_count_is_flagged_as_n_plus_1(self):
        problems = bench.check([_result(100, stmts=7), _result(1000, stmts=7), _result(5000, stmts=10_007)])
        assert len(problems) == 1 and "N+1" in problems[0] and "5000->10007" in problems[0]

    def test_superlinear_per_trade_cost_is_flagged(self):
        problems = bench.check([_result(100, ms_per_trade=0.05), _result(5000, ms_per_trade=0.5)])
        assert len(problems) == 1 and "super-linear" in problems[0]

    def test_wrong_row_count_is_flagged(self):
        problems = bench.check([_result(100), _result(1000, rows=999)])
        assert any("returned 999 rows" in p for p in problems)

    def test_ratio_threshold_is_configurable(self):
        slow = [_result(100, ms_per_trade=0.05), _result(1000, ms_per_trade=0.2)]
        assert bench.check(slow, max_per_trade_ratio=3.0) != []
        assert bench.check(slow, max_per_trade_ratio=5.0) == []


class TestCountStatements:
    def test_counts_statements_and_restores_sqlite_connect(self, tmp_path):
        import sqlite3

        original = sqlite3.connect
        db = tmp_path / "t.db"

        def work():
            c = sqlite3.connect(str(db))
            c.execute("CREATE TABLE IF NOT EXISTS t(a)")
            c.execute("INSERT INTO t VALUES (1)")
            c.commit()
            c.close()
            return "done"

        result, n = bench.count_statements(work)
        assert result == "done" and n >= 2
        assert sqlite3.connect is original  # always restored, even on success path

    def test_restores_sqlite_connect_when_fn_raises(self):
        import sqlite3

        original = sqlite3.connect
        with pytest.raises(RuntimeError):
            bench.count_statements(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        assert sqlite3.connect is original


class TestRealJournal:
    def test_statement_count_is_constant_across_sizes_and_rows_match(self):
        results = bench.run_benchmark(sizes=(20, 160), reps=1)
        assert [r.rows for r in results] == [20, 160]
        assert results[0].sql_statements == results[1].sql_statements  # exact: O(1) queries, not O(N)

    def test_agent_participation_is_populated_for_every_row(self):
        from journal.journal_v2 import TradeJournalV2

        with tempfile.TemporaryDirectory() as tmp:
            journal = TradeJournalV2(db_path=os.path.join(tmp, "b.db"))
            bench.populate(journal, 12, agents=("a", "b", "c"))
            rows = journal.get_ensemble_learning_dataset(limit=50)
        assert len(rows) == 12
        assert all(len(r["agent_participation"]) == 3 for r in rows)

    def test_healthy_baseline_passes_its_own_check(self):
        # Loose bound on purpose (noise); the exact statement-count check is the real lock.
        results = bench.run_benchmark(sizes=(100, 600), reps=2)
        assert bench.check(results, max_per_trade_ratio=6.0) == []


class TestDetectsRegression:
    def test_reintroduced_n_plus_1_is_caught(self, monkeypatch):
        """Mutation check: swap in a deliberately N+1 implementation (one extra
        query per returned row) and prove the benchmark's --check flags it."""
        from journal.journal_v2 import TradeJournalV2

        original = TradeJournalV2.get_ensemble_learning_dataset

        def n_plus_1(self, *args, **kwargs):
            rows = original(self, *args, **kwargs)
            for row in rows:  # the anti-pattern: per-row read
                self.get_trade_attribution(row["trade_id"])
            return rows

        monkeypatch.setattr(TradeJournalV2, "get_ensemble_learning_dataset", n_plus_1)
        results = bench.run_benchmark(sizes=(10, 40), reps=1)
        assert results[1].sql_statements > results[0].sql_statements
        problems = bench.check(results)
        assert any("N+1" in p for p in problems)


class TestCli:
    def test_json_output_is_machine_readable(self, capsys):
        rc = bench.main(["--sizes", "10,20", "--reps", "1", "--json"])
        out = json.loads(capsys.readouterr().out)
        assert rc == 0 and out["problems"] == []
        assert [r["trades"] for r in out["results"]] == [10, 20]

    def test_table_output_has_header_and_rows(self, capsys):
        assert bench.main(["--sizes", "10,20", "--reps", "1", "--check", "--max-per-trade-ratio", "50"]) == 0
        out = capsys.readouterr().out
        assert "sql_stmts" in out and "OK:" in out

    def test_check_requires_two_sizes(self, capsys):
        assert bench.main(["--sizes", "10", "--check"]) == 2

    def test_invalid_sizes_rejected(self):
        with pytest.raises(SystemExit):
            bench.main(["--sizes", "0,10"])

    def test_reference_loop_is_reported_when_requested(self, capsys):
        assert bench.main(["--sizes", "15", "--reps", "1", "--with-reference", "--json"]) == 0
        out = json.loads(capsys.readouterr().out)
        assert out["results"][0]["reference_ms"] is not None
