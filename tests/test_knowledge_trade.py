"""tests/test_knowledge_trade.py — V16 Phase 4C Step 8.

Uses a real TradeJournalV2 (tmp_path-backed SQLite — same established
pattern tests/test_ceo_multi_symbol_agent_attribution.py already uses)
so this suite proves real integration with Step 7C's attribution
bridge, not a mocked stand-in.
"""
from __future__ import annotations

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2
from knowledge_engine.provenance import Confidence
from knowledge_engine.trade_knowledge import ingest_closed_trade

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test_journal.db"))


def _make_closed_trade(journal, symbol="BTCUSDT", result="WIN", with_agents=True):
    signal_id = journal.save_signal(
        {"timestamp": "2026-08-11T00:00:00+00:00", "action": "LONG", "direction": "LONG", "confidence": 80.0},
        symbol=symbol,
    )
    if with_agents:
        journal.save_agent_decision(agent="smc", decision="LONG", symbol=symbol, score=75.0, weight=0.3,
                                     details={"summary": "bullish structure"}, signal_id=signal_id)
        journal.save_agent_decision(agent="futures", decision="LONG", symbol=symbol, score=65.0, weight=0.2,
                                     details={"summary": "positive funding"}, signal_id=signal_id)

    rec = TradeRecord()
    rec.symbol, rec.direction = symbol, "LONG"
    rec.entry_price, rec.stop_loss, rec.take_profit, rec.quantity = 100.0, 90.0, 120.0, 1.0
    rec.regime = "TRENDING"
    trade_id = journal.save_trade(rec, signal_id=signal_id)

    pnl = 200.0 if result == "WIN" else -100.0
    exit_price = 120.0 if result == "WIN" else 90.0
    journal.update_trade_result(trade_id, result, exit_price, pnl)
    return trade_id, signal_id


class TestClosedOnlyFilter:
    def test_open_trade_returns_none(self, journal, tmp_path):
        signal_id = journal.save_signal({"timestamp": "t", "action": "LONG", "direction": "LONG", "confidence": 50.0}, symbol="BTCUSDT")
        rec = TradeRecord()
        rec.symbol, rec.direction = "BTCUSDT", "LONG"
        trade_id = journal.save_trade(rec, signal_id=signal_id)  # never closed — result stays "OPEN"

        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)
        assert page is None
        assert not (tmp_path / "trades").exists()  # nothing written for an open trade

    def test_nonexistent_trade_returns_none(self, journal, tmp_path):
        assert ingest_closed_trade(journal, 999999, knowledge_root=tmp_path) is None

    def test_closed_trade_produces_a_page(self, journal, tmp_path):
        trade_id, _ = _make_closed_trade(journal)
        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)
        assert page is not None
        assert page.provenance.confidence is Confidence.FACT


class TestStep7CIntegration:
    def test_agent_participation_reused_not_recomputed(self, journal, tmp_path):
        """The whole point of Step 8's trade pages: agent_participation
        comes straight from journal_v2.get_trade_attribution(), which
        is only populated because Step 7C threads a shared signal_id
        through CEO_AGENT + sub-agent rows to the trade."""
        trade_id, signal_id = _make_closed_trade(journal, with_agents=True)
        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)

        assert "smc" in page.body
        assert "futures" in page.body
        assert "Phase 4C Step 7C" in page.body

    def test_trade_without_signal_id_bridge_shows_unknown_not_fabricated(self, journal, tmp_path):
        """A trade with no agent attribution must say UNKNOWN, never
        fabricate agent participation that didn't happen (spec §14)."""
        trade_id, _ = _make_closed_trade(journal, with_agents=False)
        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)

        assert "UNKNOWN" in page.body
        assert page.extra_frontmatter["signal_id_backed"] == "unknown"


class TestPageContent:
    def test_facts_are_real_field_values_not_placeholders(self, journal, tmp_path):
        trade_id, _ = _make_closed_trade(journal, symbol="ETHUSDT", result="LOSS")
        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)

        assert "ETHUSDT" in page.body
        assert "LOSS" in page.body
        assert "-100.0" in page.body

    def test_written_file_has_valid_frontmatter(self, journal, tmp_path):
        trade_id, _ = _make_closed_trade(journal)
        page = ingest_closed_trade(journal, trade_id, knowledge_root=tmp_path)
        from knowledge_engine.pages import WikiPage
        fm = WikiPage.parse_frontmatter((tmp_path / page.relative_path()).read_text(encoding="utf-8"))
        assert fm["source_type"] == "journal_trade_attribution"
        assert fm["source_id"] == str(trade_id)
