"""
tests/test_execution_attribution.py

V16 Phase 4B Step 2 (docs/architecture.md §29): Execution Attribution +
Portfolio Integration.

Covers:
  - journal/journal_v2.py's new save_execution_attribution() /
    get_trade_attribution() / get_ensemble_learning_dataset()
  - journal/trade_attribution.py's record_trade_outcome() /
    agent_attribution_from_ceo_decision()

Uses a tmp_path-backed temp-file DB per test, same reasoning as
tests/test_agent_outcome_attribution.py: database/db.py caches one
shared connection per the literal path ":memory:" for the whole
process, and these tests join across trades/agent_decisions.
"""
from __future__ import annotations

import pytest

from analytics.trade_journal import TradeRecord
from journal.journal_v2 import TradeJournalV2
from journal.trade_attribution import (
    CEO_WEIGHTED_AGENT_KEYS,
    agent_attribution_from_ceo_decision,
    record_trade_outcome,
)

pytestmark = pytest.mark.unit


def _open_trade(journal: TradeJournalV2, sig_id: int | None = None, direction: str = "LONG") -> int:
    rec = TradeRecord()
    rec.timestamp   = "2026-07-24T00:00:00+00:00"
    rec.symbol      = "BTCUSDT"
    rec.direction   = direction
    rec.entry_price = 67000.0
    rec.stop_loss   = 65800.0
    rec.take_profit = 69400.0
    rec.quantity    = 0.01
    return journal.save_trade(rec, signal_id=sig_id, execution_lane="LIVE")


@pytest.fixture
def journal(tmp_path):
    db = str(tmp_path / "test_journal.db")
    return TradeJournalV2(db_path=db)


# ══════════════════════════════════════════════════════════════════════════
# TradeJournalV2.save_execution_attribution()
# ══════════════════════════════════════════════════════════════════════════

class TestSaveExecutionAttribution:

    def test_merges_fields_into_extra_data(self, journal):
        tid = _open_trade(journal)
        ok = journal.save_execution_attribution(
            tid, execution_id="batch-1:BTCUSDT", order_id="12345", latency_seconds=0.42,
        )
        assert ok is True
        attrib = journal.get_trade_attribution(tid)
        assert attrib["execution_id"] == "batch-1:BTCUSDT"
        assert attrib["latency_seconds"] == 0.42

    def test_second_call_merges_rather_than_overwrites(self, journal):
        tid = _open_trade(journal)
        journal.save_execution_attribution(tid, execution_id="batch-1:BTCUSDT")
        journal.save_execution_attribution(tid, order_id="99")
        attrib = journal.get_trade_attribution(tid)
        assert attrib["execution_id"] == "batch-1:BTCUSDT"
        assert attrib["order_id"] == "99"

    def test_none_values_are_not_stored(self, journal):
        tid = _open_trade(journal)
        journal.save_execution_attribution(tid, execution_id="x", fees=None, slippage=None)
        attrib = journal.get_trade_attribution(tid)
        assert attrib["fees"] is None
        assert attrib["slippage"] is None

    def test_all_none_is_a_noop_and_returns_true(self, journal):
        tid = _open_trade(journal)
        assert journal.save_execution_attribution(tid, fees=None) is True

    def test_unknown_trade_id_returns_false(self, journal):
        assert journal.save_execution_attribution(99999, execution_id="x") is False


# ══════════════════════════════════════════════════════════════════════════
# TradeJournalV2.get_trade_attribution()
# ══════════════════════════════════════════════════════════════════════════

class TestGetTradeAttribution:

    def test_unknown_trade_returns_none(self, journal):
        assert journal.get_trade_attribution(99999) is None

    def test_trade_facts_present_without_any_attribution_call(self, journal):
        tid = _open_trade(journal, direction="LONG")
        attrib = journal.get_trade_attribution(tid)
        assert attrib["trade_id"] == tid
        assert attrib["symbol"] == "BTCUSDT"
        assert attrib["direction"] == "LONG"
        assert attrib["entry_price"] == 67000.0
        assert attrib["execution_id"] is None
        assert attrib["agent_participation"] == []

    def test_exit_and_pnl_reflect_update_trade_result(self, journal):
        tid = _open_trade(journal)
        journal.update_trade_result(tid, "WIN", 69000.0, 200.0)
        attrib = journal.get_trade_attribution(tid)
        assert attrib["result"] == "WIN"
        assert attrib["exit_price"] == 69000.0
        assert attrib["pnl"] == 200.0

    def test_agent_participation_derived_from_join_when_no_explicit_list(self, journal):
        """No signal_id -> agent_decisions join available (V16
        multi-symbol trades today, see module docstring) still returns
        [] honestly rather than raising."""
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("smc", "LONG", score=80.0, weight=0.25, signal_id=sig_id, execution_lane="LIVE")
        journal.save_agent_decision("regime", "SHORT", score=40.0, weight=0.15, signal_id=sig_id, execution_lane="LIVE")
        tid = _open_trade(journal, sig_id=sig_id)

        attrib = journal.get_trade_attribution(tid)
        by_agent = {a["agent"]: a for a in attrib["agent_participation"]}
        assert set(by_agent) == {"smc", "regime"}
        assert by_agent["smc"]["vote"] == "LONG"
        assert by_agent["smc"]["weight"] == 0.25
        assert by_agent["smc"]["confidence"] == 80.0
        assert by_agent["smc"]["contribution"] == pytest.approx(80.0 * 0.25, abs=0.01)

    def test_no_signal_id_gives_empty_agent_participation(self, journal):
        tid = _open_trade(journal, sig_id=None)
        attrib = journal.get_trade_attribution(tid)
        assert attrib["agent_participation"] == []

    def test_explicit_agent_attribution_takes_precedence_over_join(self, journal):
        sig_id = journal.save_signal({"action": "LONG", "direction": "LONG"}, execution_lane="LIVE")
        journal.save_agent_decision("smc", "LONG", score=80.0, weight=0.25, signal_id=sig_id, execution_lane="LIVE")
        tid = _open_trade(journal, sig_id=sig_id)

        explicit = [{"agent": "ceo", "vote": "LONG", "weight": 1.0, "confidence": 91.0, "contribution": 91.0}]
        journal.save_execution_attribution(tid, agent_attribution=explicit)

        attrib = journal.get_trade_attribution(tid)
        assert attrib["agent_participation"] == explicit


# ══════════════════════════════════════════════════════════════════════════
# TradeJournalV2.get_ensemble_learning_dataset()
# ══════════════════════════════════════════════════════════════════════════

class TestGetEnsembleLearningDataset:

    def test_empty_when_no_closed_trades(self, journal):
        assert journal.get_ensemble_learning_dataset() == []

    def test_open_trades_excluded(self, journal):
        _open_trade(journal)  # never closed -> result stays "OPEN"
        assert journal.get_ensemble_learning_dataset() == []

    def test_one_row_per_closed_trade(self, journal):
        tid1 = _open_trade(journal)
        journal.update_trade_result(tid1, "WIN", 69000.0, 200.0)
        tid2 = _open_trade(journal, direction="SHORT")
        journal.update_trade_result(tid2, "LOSS", 68000.0, -100.0)

        rows = journal.get_ensemble_learning_dataset()
        assert {r["trade_id"] for r in rows} == {tid1, tid2}

    def test_symbol_filter(self, journal):
        tid = _open_trade(journal)
        journal.update_trade_result(tid, "WIN", 69000.0, 200.0)
        assert len(journal.get_ensemble_learning_dataset(symbol="BTCUSDT")) == 1
        assert journal.get_ensemble_learning_dataset(symbol="ETHUSDT") == []

    def test_rows_with_no_agent_participation_are_included_not_filtered(self, journal):
        tid = _open_trade(journal, sig_id=None)
        journal.update_trade_result(tid, "WIN", 69000.0, 200.0)
        rows = journal.get_ensemble_learning_dataset()
        assert rows[0]["agent_participation"] == []


# ══════════════════════════════════════════════════════════════════════════
# journal.trade_attribution.record_trade_outcome()
# ══════════════════════════════════════════════════════════════════════════

class TestRecordTradeOutcome:

    def test_open_side_call_only_sets_attribution_not_result(self, journal):
        tid = _open_trade(journal)
        ok = record_trade_outcome(journal, tid, execution_id="batch-1:BTCUSDT", order_id="42")
        assert ok is True
        attrib = journal.get_trade_attribution(tid)
        assert attrib["execution_id"] == "batch-1:BTCUSDT"
        assert attrib["result"] == "OPEN"  # update_trade_result NOT called — no result/exit/pnl given

    def test_close_side_call_sets_result_and_attribution_together(self, journal):
        tid = _open_trade(journal)
        ok = record_trade_outcome(
            journal, tid,
            result="WIN", exit_price=69000.0, pnl=200.0,
            execution_id="batch-1:close:BTCUSDT", latency_seconds=0.8,
        )
        assert ok is True
        attrib = journal.get_trade_attribution(tid)
        assert attrib["result"] == "WIN"
        assert attrib["exit_price"] == 69000.0
        assert attrib["latency_seconds"] == 0.8

    def test_partial_result_fields_skips_update_trade_result(self, journal):
        """result given but not exit_price/pnl -> update_trade_result is
        NOT called (all three or none), only attribution is stored."""
        tid = _open_trade(journal)
        record_trade_outcome(journal, tid, result="WIN", execution_id="x")
        attrib = journal.get_trade_attribution(tid)
        assert attrib["result"] == "OPEN"
        assert attrib["execution_id"] == "x"

    def test_never_raises_on_broken_journal(self):
        class BrokenJournal:
            def update_trade_result(self, *a, **kw):
                raise RuntimeError("db exploded")

            def save_execution_attribution(self, *a, **kw):
                raise RuntimeError("db exploded")

        ok = record_trade_outcome(
            BrokenJournal(), 1, result="WIN", exit_price=1.0, pnl=1.0, execution_id="x",
        )
        assert ok is False  # reported, not raised

    def test_agent_attribution_passthrough(self, journal):
        tid = _open_trade(journal)
        votes = [{"agent": "smc", "vote": "LONG", "weight": 0.25, "confidence": 80.0, "contribution": 20.0}]
        record_trade_outcome(journal, tid, execution_id="x", agent_attribution=votes)
        attrib = journal.get_trade_attribution(tid)
        assert attrib["agent_participation"] == votes


# ══════════════════════════════════════════════════════════════════════════
# journal.trade_attribution.agent_attribution_from_ceo_decision()
# ══════════════════════════════════════════════════════════════════════════

class TestAgentAttributionFromCeoDecision:

    def _ceo_decision(self, **overrides) -> dict:
        base = {
            "action": "LONG",
            "confidence": 72.5,
            "agent_reports": {
                "smc":    {"signal": "LONG", "confidence": 80.0},
                "regime": {"signal": "SHORT", "confidence": 30.0},
            },
            "weights_used": {"smc": 0.25, "regime": 0.15},
            "score_breakdown": {"smc": 20.0, "regime": 4.5},
        }
        base.update(overrides)
        return base

    def test_none_input_returns_empty_list(self):
        assert agent_attribution_from_ceo_decision(None) == []

    def test_empty_dict_returns_empty_list(self):
        assert agent_attribution_from_ceo_decision({}) == []

    def test_extracts_one_entry_per_reporting_agent(self):
        out = agent_attribution_from_ceo_decision(self._ceo_decision())
        by_agent = {e["agent"]: e for e in out}
        assert by_agent["smc"] == {
            "agent": "smc", "vote": "LONG", "weight": 0.25,
            "confidence": 80.0, "contribution": 20.0,
        }
        assert by_agent["regime"]["vote"] == "SHORT"

    def test_non_reporting_agent_omitted_not_fabricated(self):
        """Only smc/regime reported this cycle (per fixture) — the other
        four CEO_WEIGHTED_AGENT_KEYS must NOT appear as zeroed entries."""
        out = agent_attribution_from_ceo_decision(self._ceo_decision())
        agents = {e["agent"] for e in out}
        for key in CEO_WEIGHTED_AGENT_KEYS:
            if key not in ("smc", "regime"):
                assert key not in agents

    def test_ceo_aggregate_entry_included_with_weight_one(self):
        out = agent_attribution_from_ceo_decision(self._ceo_decision())
        ceo_entries = [e for e in out if e["agent"] == "ceo"]
        assert len(ceo_entries) == 1
        ceo = ceo_entries[0]
        assert ceo["vote"] == "LONG"
        assert ceo["weight"] == 1.0
        assert ceo["confidence"] == 72.5
        assert ceo["contribution"] == 72.5

    def test_no_action_key_omits_ceo_entry(self):
        decision = self._ceo_decision()
        del decision["action"]
        out = agent_attribution_from_ceo_decision(decision)
        assert all(e["agent"] != "ceo" for e in out)
