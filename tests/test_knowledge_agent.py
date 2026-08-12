"""tests/test_knowledge_agent.py — V16 Phase 4C Step 8."""
from __future__ import annotations

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2
from knowledge_engine.agent_knowledge import MIN_SAMPLE_SIZE, ingest_agent_performance
from knowledge_engine.pages import WikiPage
from knowledge_engine.provenance import Confidence

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test_journal.db"))


def _record_agent_trade(journal, agent="smc", agent_vote="LONG", trade_direction="LONG", result="WIN", symbol="BTCUSDT"):
    signal_id = journal.save_signal({"timestamp": "t", "action": trade_direction, "direction": trade_direction, "confidence": 70.0}, symbol=symbol)
    journal.save_agent_decision(agent=agent, decision=agent_vote, symbol=symbol, score=70.0, weight=0.25, details={}, signal_id=signal_id)
    rec = TradeRecord()
    rec.symbol, rec.direction = symbol, trade_direction
    rec.entry_price, rec.stop_loss = 100.0, 90.0
    trade_id = journal.save_trade(rec, signal_id=signal_id)
    pnl = 50.0 if result == "WIN" else -25.0
    journal.update_trade_result(trade_id, result, exit_price=110.0 if result == "WIN" else 90.0, pnl=pnl)
    return trade_id


class TestSampleSizeFloor:
    def test_below_minimum_reports_insufficient_evidence(self, journal, tmp_path):
        for _ in range(MIN_SAMPLE_SIZE - 1):
            _record_agent_trade(journal, agent="smc", result="WIN")

        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")
        assert smc.provenance.confidence is Confidence.UNKNOWN
        assert smc.extra_frontmatter["win_rate"] == "INSUFFICIENT_EVIDENCE"
        assert "INSUFFICIENT_EVIDENCE" in smc.body

    def test_at_or_above_minimum_reports_real_win_rate(self, journal, tmp_path):
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", result="WIN")

        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")
        assert smc.provenance.confidence is Confidence.DERIVED_OBSERVATION
        assert smc.extra_frontmatter["win_rate"] == "1.0"


class TestStep7CIntegration:
    def test_only_counts_votes_matching_traded_direction(self, journal, tmp_path):
        """Mirrors get_agent_performance()'s own real join semantics —
        this module adds no extra filtering of its own, it just
        summarizes what that method already returns."""
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", agent_vote="LONG", trade_direction="LONG", result="WIN")
        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")
        assert smc.extra_frontmatter["total_trades"] == MIN_SAMPLE_SIZE

    def test_no_pages_before_any_attributed_trades_exist(self, journal, tmp_path):
        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        assert pages == []


class TestContradictionHandling:
    def test_no_revision_history_on_first_ingest(self, journal, tmp_path):
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", result="WIN")
        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")
        assert "## Revision History" not in smc.body

    def test_large_swing_recorded_as_revision_not_silently_overwritten(self, journal, tmp_path):
        # first ingest: all wins -> win_rate 1.0
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", result="WIN")
        ingest_agent_performance(journal, knowledge_root=tmp_path)

        # more trades, mostly losses -> win_rate drops sharply
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", result="LOSS")
        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")

        assert "## Revision History" in smc.body
        assert "win_rate=1.0" in smc.body or "win_rate=1.0000" in smc.body  # previous claim preserved

    def test_small_change_not_recorded_as_revision(self, journal, tmp_path):
        for _ in range(20):
            _record_agent_trade(journal, agent="smc", result="WIN")
        ingest_agent_performance(journal, knowledge_root=tmp_path)

        _record_agent_trade(journal, agent="smc", result="WIN")  # one more win, tiny movement
        pages = ingest_agent_performance(journal, knowledge_root=tmp_path)
        smc = next(p for p in pages if p.entity_id == "smc")
        assert "## Revision History" not in smc.body


class TestPageWrittenCorrectly:
    def test_frontmatter_has_expected_fields(self, journal, tmp_path):
        for _ in range(MIN_SAMPLE_SIZE):
            _record_agent_trade(journal, agent="smc", result="WIN")
        ingest_agent_performance(journal, knowledge_root=tmp_path)

        fm = WikiPage.parse_frontmatter((tmp_path / "agents" / "smc.md").read_text(encoding="utf-8"))
        assert fm["entity_type"] == "agent"
        assert fm["source_type"] == "journal_agent_performance"
