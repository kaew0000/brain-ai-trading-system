"""
tests/test_agent_performance_attribution.py

V16 Phase 4C Track A: TradeJournalV2.get_agent_performance() previously
only aggregated attribution via the Step 7C agent_decisions <-> trades
join (see tests/test_agent_outcome_attribution.py). Trades taken through
the default V16 multi-symbol execution path never populate signal_id,
so their per-agent participation — already correctly stored and already
correctly returned by get_trade_attribution() via the W14-2A
trades.extra_data.attribution.agent_attribution path — never contributed
any rows to get_agent_performance()'s aggregate.

This suite covers the fix: get_agent_performance() must aggregate BOTH
attribution sources by reusing get_trade_attribution()'s own existing
precedence per trade (explicit agent_attribution wins over the
signal_id join; a trade is never counted via both).
"""

from __future__ import annotations

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2

pytestmark = pytest.mark.unit


def _open_trade(journal: TradeJournalV2, direction: str, signal_id: int | None = None) -> int:
    rec = TradeRecord()
    rec.timestamp   = "2026-07-23T00:00:00+00:00"
    rec.direction   = direction
    rec.entry_price = 67000.0
    rec.stop_loss   = 65800.0
    rec.take_profit = 69400.0
    return journal.save_trade(rec, execution_lane="LIVE", signal_id=signal_id)


@pytest.fixture
def journal(tmp_path):
    """Fresh, isolated TradeJournalV2 — see test_agent_outcome_attribution.py's
    fixture docstring for why a real tmp-file db (not ':memory:') is required."""
    db = str(tmp_path / "test_journal.db")
    return TradeJournalV2(db_path=db)


class TestExplicitAttributionPath:
    """Test A: W14-2A explicit attribution, signal_id=None."""

    def test_explicit_attribution_populates_performance(self, journal):
        tid = _open_trade(journal, "LONG")  # signal_id=None, the default V16 path
        journal.update_trade_result(tid, "WIN", 69000.0, 250.0)
        journal.save_execution_attribution(
            tid,
            agent_attribution=[
                {"agent": "ceo", "vote": "LONG", "weight": 1.0,
                 "confidence": 82.0, "contribution": 82.0},
                {"agent": "smc", "vote": "LONG", "weight": 0.3,
                 "confidence": 80.0, "contribution": 24.0},
            ],
        )

        # Sanity: the previously-working single-trade read already saw this.
        attribution = journal.get_trade_attribution(tid)
        assert len(attribution["agent_participation"]) == 2

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert perf.keys() == {"ceo", "smc"}
        assert perf["ceo"]["total_trades"] == 1
        assert perf["ceo"]["wins"] == 1
        assert perf["ceo"]["losses"] == 0
        assert perf["ceo"]["win_rate"] == 1.0
        assert perf["ceo"]["total_pnl"] == 250.0
        assert perf["smc"]["total_trades"] == 1
        assert perf["smc"]["total_pnl"] == 250.0

    def test_explicit_attribution_dissenting_vote_not_attributed(self, journal):
        tid = _open_trade(journal, "LONG")
        journal.update_trade_result(tid, "LOSS", 65800.0, -120.0)
        journal.save_execution_attribution(
            tid,
            agent_attribution=[
                {"agent": "ceo", "vote": "SHORT", "weight": 1.0,
                 "confidence": 55.0, "contribution": 55.0},
            ],
        )
        assert journal.get_agent_performance() == []

    def test_explicit_attribution_multiple_trades_aggregate(self, journal):
        t1 = _open_trade(journal, "LONG")
        journal.update_trade_result(t1, "WIN", 69000.0, 300.0)
        journal.save_execution_attribution(
            t1, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                     "confidence": 80.0, "contribution": 80.0}])

        t2 = _open_trade(journal, "LONG")
        journal.update_trade_result(t2, "LOSS", 65800.0, -150.0)
        journal.save_execution_attribution(
            t2, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                     "confidence": 60.0, "contribution": 60.0}])

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert perf["ceo"]["total_trades"] == 2
        assert perf["ceo"]["wins"] == 1
        assert perf["ceo"]["losses"] == 1
        assert perf["ceo"]["win_rate"] == 0.5
        assert perf["ceo"]["total_pnl"] == 150.0


class TestStep7CPathUnchanged:
    """Test B: existing agent_decisions/signal_id path — behavior must be
    identical to tests/test_agent_outcome_attribution.py."""

    def test_step7c_path_still_works(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("SMC_ANALYST", "LONG", score=80.0, weight=0.25,
                                     signal_id=sig_id, execution_lane="LIVE")
        tid = _open_trade(journal, "LONG", signal_id=sig_id)
        journal.update_trade_result(tid, "WIN", 69000.0, 250.0)

        perf = journal.get_agent_performance()
        assert len(perf) == 1
        row = perf[0]
        assert row["agent"] == "SMC_ANALYST"
        assert row["total_trades"] == 1
        assert row["wins"] == 1
        assert row["win_rate"] == 1.0
        assert row["total_pnl"] == 250.0

    def test_step7c_dissenting_agent_not_attributed(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("SMC_ANALYST", "LONG", score=80.0, weight=0.25,
                                     signal_id=sig_id, execution_lane="LIVE")
        journal.save_agent_decision("REGIME_ANALYST", "SHORT", score=55.0, weight=0.15,
                                     signal_id=sig_id, execution_lane="LIVE")
        tid = _open_trade(journal, "LONG", signal_id=sig_id)
        journal.update_trade_result(tid, "LOSS", 65800.0, -120.0)

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert "SMC_ANALYST" in perf
        assert perf["SMC_ANALYST"]["losses"] == 1
        assert "REGIME_ANALYST" not in perf


class TestMixedDatabase:
    """Test C: both attribution types in the same database — each
    eligible trade must be represented exactly once."""

    def test_mixed_paths_both_aggregate(self, journal):
        # Step 7C trade
        sig_id = journal.save_signal({"action": "SHORT", "direction": "SHORT"}, execution_lane="LIVE")
        journal.save_agent_decision("REGIME_ANALYST", "SHORT", score=70.0, weight=0.2,
                                     signal_id=sig_id, execution_lane="LIVE")
        t1 = _open_trade(journal, "SHORT", signal_id=sig_id)
        journal.update_trade_result(t1, "LOSS", 68000.0, -80.0)

        # W14-2A trade
        t2 = _open_trade(journal, "LONG")
        journal.update_trade_result(t2, "WIN", 69000.0, 250.0)
        journal.save_execution_attribution(
            t2, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                     "confidence": 82.0, "contribution": 82.0}])

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert perf.keys() == {"REGIME_ANALYST", "ceo"}
        assert perf["REGIME_ANALYST"]["losses"] == 1
        assert perf["REGIME_ANALYST"]["total_pnl"] == -80.0
        assert perf["ceo"]["wins"] == 1
        assert perf["ceo"]["total_pnl"] == 250.0


class TestDuplicateAttributionProtection:
    """Test D: a trade carrying BOTH signal_id->agent_decisions AND an
    explicit extra_data.attribution.agent_attribution must not be counted
    twice — must follow get_trade_attribution()'s existing precedence
    (explicit wins, join-derived participants for that trade are ignored)."""

    def test_dual_source_trade_not_double_counted(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("FUTURES_ANALYST", "LONG", score=60.0, weight=0.2,
                                     signal_id=sig_id, execution_lane="LIVE")
        tid = _open_trade(journal, "LONG", signal_id=sig_id)
        journal.update_trade_result(tid, "WIN", 70000.0, 300.0)
        journal.save_execution_attribution(
            tid, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                      "confidence": 90.0, "contribution": 90.0}])

        # Precedence check on the single-trade read this method reuses.
        attribution = journal.get_trade_attribution(tid)
        participants = {p["agent"] for p in attribution["agent_participation"]}
        assert participants == {"ceo"}  # explicit wins; FUTURES_ANALYST join is not used

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert "FUTURES_ANALYST" not in perf
        assert perf["ceo"]["total_trades"] == 1
        assert perf["ceo"]["total_pnl"] == 300.0

    def test_dual_source_trade_combined_with_others_no_double_count(self, journal):
        """Same dual-source trade, plus a pure explicit trade for the same
        agent — total_trades for 'ceo' must be exactly 2, not 3+."""
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("FUTURES_ANALYST", "LONG", score=60.0, weight=0.2,
                                     signal_id=sig_id, execution_lane="LIVE")
        t1 = _open_trade(journal, "LONG", signal_id=sig_id)
        journal.update_trade_result(t1, "WIN", 70000.0, 300.0)
        journal.save_execution_attribution(
            t1, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                     "confidence": 90.0, "contribution": 90.0}])

        t2 = _open_trade(journal, "LONG")
        journal.update_trade_result(t2, "WIN", 69000.0, 250.0)
        journal.save_execution_attribution(
            t2, agent_attribution=[{"agent": "ceo", "vote": "LONG", "weight": 1.0,
                                     "confidence": 82.0, "contribution": 82.0}])

        perf = {row["agent"]: row for row in journal.get_agent_performance()}
        assert perf["ceo"]["total_trades"] == 2
        assert perf["ceo"]["total_pnl"] == 550.0
        assert "FUTURES_ANALYST" not in perf
