"""tests/test_ensemble_dataset_bulk_fetch.py — V16 §63.

journal/journal_v2.py::get_ensemble_learning_dataset() called
get_trade_attribution(trade_id) once per row — 2 queries per trade
(the trade row, its agent_decisions), ~28.5s at 10,000 trades. Fixed
to fetch both in bulk (2 queries total, regardless of row count) and
shape each row through the same _shape_trade_attribution() helper
get_trade_attribution() itself now uses, so the two methods' output
can't silently drift apart from each other — the original design's
whole reason for the N+1 reuse it replaces (see
get_ensemble_learning_dataset()'s own docstring, pre-§63, in git
history).

This file covers what the pre-existing get_ensemble_learning_dataset()
tests in tests/test_execution_attribution.py don't: the query-count fix
itself, and byte-for-byte output equivalence against
get_trade_attribution() across every shape variation that method
handles (no signal_id, signal_id with no agent_decisions rows, several
agents, explicit agent_attribution override).
"""
from __future__ import annotations

import sqlite3

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2

pytestmark = pytest.mark.unit


def _open_trade(journal: TradeJournalV2, sig_id: int | None = None, symbol: str = "BTCUSDT") -> int:
    rec = TradeRecord()
    rec.timestamp   = "2026-07-24T00:00:00+00:00"
    rec.symbol      = symbol
    rec.direction   = "LONG"
    rec.entry_price = 67000.0
    rec.stop_loss   = 65800.0
    rec.take_profit = 69400.0
    rec.quantity    = 0.01
    return journal.save_trade(rec, signal_id=sig_id, execution_lane="LIVE")


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


class _QueryCounter:
    """Counts SQL statements executed on any connection created for the
    duration of the `with` block, via sqlite3's own trace-callback
    mechanism (sqlite3.Connection is a C/immutable type — its methods
    can't be monkeypatched directly, but sqlite3.connect() itself is an
    ordinary, patchable module function). Self-contained save/restore
    (not routed through pytest's monkeypatch.undo(), which is a single
    blanket undo per fixture instance) so multiple counters can be used
    back-to-back within one test without one's patch leaking into the
    next's measurement."""
    def __init__(self, monkeypatch=None):
        self.count = 0
        self._original_connect = None

    def __enter__(self):
        self._original_connect = sqlite3.connect
        def counting_connect(*args, **kwargs):
            conn = self._original_connect(*args, **kwargs)
            conn.set_trace_callback(lambda sql: setattr(self, "count", self.count + 1))
            return conn
        sqlite3.connect = counting_connect
        return self

    def __exit__(self, *exc):
        sqlite3.connect = self._original_connect
        return False


def _seed_closed_trade(journal, symbol="BTCUSDT", n_agents=0, explicit_attribution=None):
    sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE") \
        if n_agents or explicit_attribution else None
    for i in range(n_agents):
        journal.save_agent_decision(
            f"agent{i}", "LONG", score=70.0 + i, weight=0.1 + i * 0.05,
            signal_id=sig_id, execution_lane="LIVE",
        )
    tid = _open_trade(journal, sig_id=sig_id, symbol=symbol)
    if explicit_attribution is not None:
        journal.save_execution_attribution(tid, agent_attribution=explicit_attribution)
    journal.update_trade_result(tid, "WIN", 68000.0, 123.45)
    return tid


class TestQueryCountIsConstant:
    """Compares the count between two different trade counts rather
    than asserting an exact number -- sqlite3's own connection-setup
    PRAGMAs (WAL mode, busy_timeout, etc. -- see database/db.py's
    _new_file_conn()) are traced by set_trace_callback too, so the
    absolute count includes fixed per-connection overhead unrelated to
    this fix. What actually matters, and what this isolates: whether
    the count SCALES with the number of trades (the N+1 bug) or stays
    flat (the fix)."""

    def test_query_count_does_not_scale_with_trade_count(self, journal, monkeypatch, tmp_path):
        journal_small = journal
        for _ in range(3):
            _seed_closed_trade(journal_small, n_agents=2)
        with _QueryCounter(monkeypatch) as qc_small:
            rows_small = journal_small.get_ensemble_learning_dataset(limit=1000)
        assert len(rows_small) == 3

        journal_large = TradeJournalV2(db_path=str(tmp_path / "test_large.db"))
        for _ in range(30):
            _seed_closed_trade(journal_large, n_agents=2)
        with _QueryCounter(monkeypatch) as qc_large:
            rows_large = journal_large.get_ensemble_learning_dataset(limit=1000)
        assert len(rows_large) == 30

        # 10x the trades, but the SAME query count -- under the pre-§63
        # per-row reuse this would have been roughly 10x higher instead
        # (1 + 2*3 = 7 vs 1 + 2*30 = 61).
        assert qc_large.count == qc_small.count

    def test_single_row_get_trade_attribution_unaffected_by_this_fix(self, journal, monkeypatch):
        """get_trade_attribution() itself must cost the same regardless
        of how many OTHER trades exist -- this fix only changes the
        bulk method's query pattern, not the single-row one."""
        tid_first = _seed_closed_trade(journal, n_agents=1)
        with _QueryCounter(monkeypatch) as qc_few:
            journal.get_trade_attribution(tid_first)

        for _ in range(20):
            _seed_closed_trade(journal, n_agents=1)
        with _QueryCounter(monkeypatch) as qc_many:
            journal.get_trade_attribution(tid_first)

        assert qc_many.count == qc_few.count


class TestBulkOutputMatchesSingleRowExactly:
    """The critical regression guard: every row get_ensemble_learning_
    dataset() produces must be byte-for-byte identical to what
    get_trade_attribution(trade_id) returns for that same trade --
    proving the two shapes truly cannot drift apart, across every shape
    variation get_trade_attribution() itself handles."""

    def test_no_signal_id(self, journal):
        tid = _seed_closed_trade(journal, n_agents=0)
        bulk = journal.get_ensemble_learning_dataset(limit=10)
        single = journal.get_trade_attribution(tid)
        assert bulk == [single]

    def test_signal_id_with_no_agent_decisions_rows(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        tid = _open_trade(journal, sig_id=sig_id)
        journal.update_trade_result(tid, "LOSS", 66000.0, -50.0)
        bulk = journal.get_ensemble_learning_dataset(limit=10)
        single = journal.get_trade_attribution(tid)
        assert single["agent_participation"] == []
        assert bulk == [single]

    def test_several_agents_multiple_trades(self, journal):
        tids = [
            _seed_closed_trade(journal, n_agents=3),
            _seed_closed_trade(journal, n_agents=1),
            _seed_closed_trade(journal, n_agents=0),
        ]
        bulk = journal.get_ensemble_learning_dataset(limit=10)
        singles = [journal.get_trade_attribution(tid) for tid in tids]
        # Order-independent comparison (bulk is DESC by timestamp; ties
        # on an identical timestamp fixture aren't guaranteed stable).
        assert {r["trade_id"] for r in bulk} == {s["trade_id"] for s in singles}
        by_id_bulk = {r["trade_id"]: r for r in bulk}
        for s in singles:
            assert by_id_bulk[s["trade_id"]] == s

    def test_explicit_agent_attribution_override(self, journal):
        explicit = [{"agent": "smc", "vote": "LONG", "weight": 1.0, "confidence": 90.0, "contribution": 90.0}]
        tid = _seed_closed_trade(journal, n_agents=2, explicit_attribution=explicit)
        bulk = journal.get_ensemble_learning_dataset(limit=10)
        single = journal.get_trade_attribution(tid)
        assert single["agent_participation"] == explicit
        assert bulk == [single]

    def test_symbol_filter_matches_single_row_subset(self, journal):
        btc_tid = _seed_closed_trade(journal, symbol="BTCUSDT", n_agents=1)
        _seed_closed_trade(journal, symbol="XRPUSDT", n_agents=1)
        bulk = journal.get_ensemble_learning_dataset(limit=10, symbol="BTCUSDT")
        assert len(bulk) == 1
        assert bulk[0] == journal.get_trade_attribution(btc_tid)

    def test_empty_dataset(self, journal):
        assert journal.get_ensemble_learning_dataset(limit=10) == []

    def test_open_trades_excluded_from_bulk_too(self, journal):
        _open_trade(journal)   # never closed
        assert journal.get_ensemble_learning_dataset(limit=10) == []
