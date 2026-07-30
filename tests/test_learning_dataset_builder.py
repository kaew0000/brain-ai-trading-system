"""
tests/test_learning_dataset_builder.py — V16 Phase 4C Step 1

Uses a tmp_path-backed temp-file DB per test (database/db.py caches one
shared connection per the literal path ":memory:" for the whole
process — same reasoning as tests/test_agent_outcome_attribution.py
and tests/test_execution_attribution.py).
"""
from __future__ import annotations

import pytest

from journal.journal_v2 import TradeJournalV2
from learning.dataset_builder import LearningDataset, LearningDatasetBuilder, LearningRow
from tests._learning_helpers import seed_trades

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


class TestEmptyDataset:

    def test_empty_journal_returns_empty_dataset(self, journal):
        dataset = LearningDatasetBuilder(journal).build()
        assert isinstance(dataset, LearningDataset)
        assert dataset.row_count == 0
        assert dataset.rows == ()

    def test_len_matches_row_count(self, journal):
        dataset = LearningDatasetBuilder(journal).build()
        assert len(dataset) == 0


class TestBuildFromRealTrades:

    def test_row_count_matches_seeded_trades(self, journal):
        seed_trades(journal, 10)
        dataset = LearningDatasetBuilder(journal).build()
        assert dataset.row_count == 10

    def test_rows_are_learning_row_instances(self, journal):
        seed_trades(journal, 3)
        dataset = LearningDatasetBuilder(journal).build()
        assert all(isinstance(r, LearningRow) for r in dataset.rows)

    def test_rows_is_a_tuple_not_a_list(self, journal):
        """Real immutability, not just a frozen dataclass wrapping a
        mutable list a caller could still .append() to."""
        seed_trades(journal, 3)
        dataset = LearningDatasetBuilder(journal).build()
        assert isinstance(dataset.rows, tuple)

    def test_dataset_is_frozen(self, journal):
        seed_trades(journal, 1)
        dataset = LearningDatasetBuilder(journal).build()
        with pytest.raises(Exception):
            dataset.row_count = 999

    def test_trade_facts_present(self, journal):
        seed_trades(journal, 1)
        dataset = LearningDatasetBuilder(journal).build()
        row = dataset.rows[0]
        assert row.symbol == "BTCUSDT"
        assert row.direction == "LONG"
        assert row.result in ("WIN", "LOSS")
        assert row.pnl is not None
        assert row.regime is not None

    def test_execution_attribution_present(self, journal):
        seed_trades(journal, 1)
        row = LearningDatasetBuilder(journal).build().rows[0]
        assert row.latency_seconds is not None
        assert row.reason == "SL_TP"
        assert row.source == "trade_lifecycle"
        assert row.duration_seconds is not None

    def test_agent_participation_and_ceo_decision_extracted(self, journal):
        seed_trades(journal, 1, with_agents=True)
        row = LearningDatasetBuilder(journal).build().rows[0]
        assert len(row.agent_participation) == 3  # smc, regime, ceo
        assert row.ceo_decision is not None
        assert row.ceo_decision["agent"] == "ceo"
        assert "smc" in row.ensemble_weights
        assert "ceo" not in row.ensemble_weights  # CEO pulled out into ceo_decision, not double-counted as a weighted agent

    def test_no_agents_gives_empty_participation(self, journal):
        seed_trades(journal, 1, with_agents=False)
        row = LearningDatasetBuilder(journal).build().rows[0]
        assert row.agent_participation == []
        assert row.ceo_decision is None
        assert row.ensemble_weights == {}

    def test_journal_references_traceable(self, journal):
        seed_trades(journal, 1)
        row = LearningDatasetBuilder(journal).build().rows[0]
        assert row.journal_references["trade_id"] == row.trade_id
        assert row.journal_references["order_id"]
        assert row.journal_references["execution_id"]

    def test_symbol_filter(self, journal):
        seed_trades(journal, 9)  # 3 symbols x 3 each
        dataset = LearningDatasetBuilder(journal).build(symbol="ETHUSDT")
        assert dataset.row_count == 3
        assert all(r.symbol == "ETHUSDT" for r in dataset.rows)

    def test_limit_respected(self, journal):
        seed_trades(journal, 20)
        dataset = LearningDatasetBuilder(journal).build(limit=5)
        assert dataset.row_count == 5


class TestFieldsNotYetPopulated:
    """These fields are documented as always-None today (see
    dataset_builder.py's module docstring) — not fabricated, not
    silently omitted."""

    def test_market_context_and_indicator_fields_are_none(self, journal):
        seed_trades(journal, 1)
        row = LearningDatasetBuilder(journal).build().rows[0]
        assert row.market_context is None
        assert row.volatility is None
        assert row.atr is None
        assert row.spread is None


class TestDerivedSequenceFields:

    def test_rows_are_chronologically_ordered(self, journal):
        seed_trades(journal, 15)
        dataset = LearningDatasetBuilder(journal).build()
        timestamps = [r.timestamp for r in dataset.rows]
        assert timestamps == sorted(timestamps)

    def test_sequence_index_increments(self, journal):
        seed_trades(journal, 5)
        dataset = LearningDatasetBuilder(journal).build()
        assert [r.sequence_index for r in dataset.rows] == [0, 1, 2, 3, 4]

    def test_cumulative_pnl_is_running_sum(self, journal):
        seed_trades(journal, 8)
        dataset = LearningDatasetBuilder(journal).build()
        running = 0.0
        for row in dataset.rows:
            running += row.pnl
            assert row.cumulative_pnl == pytest.approx(round(running, 4))

    def test_running_drawdown_never_positive(self, journal):
        seed_trades(journal, 20, win_rate=0.3)  # more losses -> real drawdown to check
        dataset = LearningDatasetBuilder(journal).build()
        assert all(r.running_drawdown <= 0 for r in dataset.rows)

    def test_running_drawdown_zero_at_new_equity_high(self, journal):
        seed_trades(journal, 20, win_rate=0.9)
        dataset = LearningDatasetBuilder(journal).build()
        # With a high win rate, at least one row should be a new equity high (drawdown == 0)
        assert any(r.running_drawdown == 0 for r in dataset.rows)


class TestNeverRaises:

    def test_journal_read_failure_returns_empty_dataset_not_an_exception(self):
        class BrokenJournal:
            def get_ensemble_learning_dataset(self, **kwargs):
                raise RuntimeError("db exploded")

        dataset = LearningDatasetBuilder(BrokenJournal()).build()
        assert dataset.row_count == 0
        assert dataset.rows == ()


class TestToDicts:

    def test_to_dicts_is_json_shaped(self, journal):
        seed_trades(journal, 2)
        dataset = LearningDatasetBuilder(journal).build()
        dicts = dataset.to_dicts()
        assert len(dicts) == 2
        assert isinstance(dicts[0], dict)
        assert dicts[0]["symbol"] == dataset.rows[0].symbol
