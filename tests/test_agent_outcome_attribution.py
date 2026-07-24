"""
tests/test_agent_outcome_attribution.py

Phase 4B Step 1 (architecture.md §27): per-agent outcome attribution.

Covers TradeJournalV2.get_agent_performance(), which joins the existing
agent_decisions.signal_id <-> trades.signal_id linkage (already in the V13
schema, never populated by the live pipeline before this phase) to compute
each agent's real win/loss record — only counting a vote toward its agent
when that vote's direction matches the direction actually traded.

Does NOT test main.py's cycle wiring directly (no unit-test seam for the
live trading loop); exercises the same journal call sequence main.py now
makes: save_signal -> save_agent_decision(signal_id=...) ->
save_trade(signal_id=...) -> update_trade_result.
"""

from __future__ import annotations

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2

pytestmark = pytest.mark.unit


def _open_trade(journal: TradeJournalV2, sig_id: int, direction: str) -> int:
    rec = TradeRecord()
    rec.timestamp   = "2026-07-23T00:00:00+00:00"
    rec.direction   = direction
    rec.entry_price = 67000.0
    rec.stop_loss   = 65800.0
    rec.take_profit = 69400.0
    return journal.save_trade(rec, signal_id=sig_id)


class TestAgentPerformance:

    @pytest.fixture
    def journal(self, tmp_path):
        """A fresh TradeJournalV2 backed by its own temp SQLite file.

        Deliberately NOT db_path=":memory:" — database/db.py caches one
        shared connection per the literal path ":memory:" for the whole
        process (see its own docstring), so every ":memory:" journal in
        the test suite is actually the same database. get_agent_performance()
        joins across the whole agent_decisions/trades tables, so these tests
        need real per-test isolation, matching the tmp_journal pattern
        already used in tests/test_execution.py.
        """
        db = str(tmp_path / "test_journal.db")
        return TradeJournalV2(db_path=db)

    def test_empty_when_no_data(self, journal):
        assert journal.get_agent_performance() == []

    def test_agreeing_agent_credited_with_win(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"})
        journal.save_agent_decision("SMC_ANALYST", "LONG", score=80.0, weight=0.25,
                                     signal_id=sig_id)
        tid = _open_trade(journal, sig_id, "LONG")
        journal.update_trade_result(tid, "WIN", 69000.0, 250.0)

        perf = journal.get_agent_performance()
        assert len(perf) == 1
        row = perf[0]
        assert row["agent"] == "SMC_ANALYST"
        assert row["total_trades"] == 1
        assert row["wins"] == 1
        assert row["losses"] == 0
        assert row["win_rate"] == 1.0
        assert row["total_pnl"] == 250.0

    def test_dissenting_agent_not_attributed_either_way(self, journal):
        """An agent that voted the opposite direction of the trade actually
        taken should not show up in the winner's performance row nor be
        blamed for the loss — it didn't get the trade it voted for."""
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"})
        journal.save_agent_decision("SMC_ANALYST", "LONG", score=80.0, weight=0.25,
                                     signal_id=sig_id)
        journal.save_agent_decision("REGIME_ANALYST", "SHORT", score=55.0, weight=0.15,
                                     signal_id=sig_id)
        tid = _open_trade(journal, sig_id, "LONG")
        journal.update_trade_result(tid, "LOSS", 65800.0, -120.0)

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert "SMC_ANALYST" in perf
        assert perf["SMC_ANALYST"]["losses"] == 1
        assert "REGIME_ANALYST" not in perf

    def test_win_rate_across_multiple_trades(self, journal):
        sig1 = journal.save_signal({"action": "LONG", "direction": "LONG"})
        journal.save_agent_decision("FUTURES_ANALYST", "LONG", signal_id=sig1)
        t1 = _open_trade(journal, sig1, "LONG")
        journal.update_trade_result(t1, "WIN", 69000.0, 300.0)

        sig2 = journal.save_signal({"action": "LONG", "direction": "LONG"})
        journal.save_agent_decision("FUTURES_ANALYST", "LONG", signal_id=sig2)
        t2 = _open_trade(journal, sig2, "LONG")
        journal.update_trade_result(t2, "LOSS", 65800.0, -150.0)

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        fa = perf["FUTURES_ANALYST"]
        assert fa["total_trades"] == 2
        assert fa["wins"] == 1
        assert fa["losses"] == 1
        assert fa["win_rate"] == 0.5
        assert fa["total_pnl"] == 150.0

    def test_open_trades_excluded(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"})
        journal.save_agent_decision("SMC_ANALYST", "LONG", signal_id=sig_id)
        _open_trade(journal, sig_id, "LONG")  # left OPEN, never closed

        assert journal.get_agent_performance() == []

    def test_agent_decision_without_signal_id_ignored(self, journal):
        """Agent votes recorded with no signal_id (e.g. legacy/manual calls)
        must not crash the join and must not be attributed anything."""
        journal.save_agent_decision("SMC_ANALYST", "LONG")  # signal_id=None
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"})
        tid = _open_trade(journal, sig_id, "LONG")
        journal.update_trade_result(tid, "WIN", 69000.0, 250.0)

        assert journal.get_agent_performance() == []

    def test_limit_respected(self, journal):
        for i in range(3):
            sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"})
            journal.save_agent_decision(f"AGENT_{i}", "LONG", signal_id=sig_id)
            tid = _open_trade(journal, sig_id, "LONG")
            journal.update_trade_result(tid, "WIN", 69000.0, 100.0)

        assert len(journal.get_agent_performance(limit=2)) == 2
        assert len(journal.get_agent_performance(limit=10)) == 3
