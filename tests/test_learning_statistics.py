"""
tests/test_learning_statistics.py — V16 Phase 4C Step 1: symbol_statistics.py,
regime_statistics.py, agent_statistics.py, feature_statistics.py,
performance_tracker.py.
"""
from __future__ import annotations

import pytest

from journal.journal_v2 import TradeJournalV2
from learning.agent_statistics import compute_agent_statistics
from learning.dataset_builder import LearningDatasetBuilder
from learning.feature_statistics import compute_feature_statistics
from learning.performance_tracker import PerformanceTracker, compute_performance_report
from learning.regime_statistics import compute_regime_statistics
from learning.symbol_statistics import compute_symbol_statistics
from tests._learning_helpers import seed_trades

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


@pytest.fixture
def dataset(journal):
    seed_trades(journal, 30)
    return LearningDatasetBuilder(journal).build()


# ══════════════════════════════════════════════════════════════════════════
# symbol_statistics
# ══════════════════════════════════════════════════════════════════════════

class TestSymbolStatistics:

    def test_empty_dataset_gives_empty_list(self):
        assert compute_symbol_statistics([]) == []

    def test_one_entry_per_symbol_seeded(self, dataset):
        stats = compute_symbol_statistics(dataset)
        assert {s.symbol for s in stats} == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_sorted_best_first(self, dataset):
        stats = compute_symbol_statistics(dataset)
        pnls = [s.stats["total_pnl"] for s in stats]
        assert pnls == sorted(pnls, reverse=True)

    def test_accepts_raw_rows_not_just_a_dataset(self, dataset):
        """Every public function in learning/ accepts either a
        LearningDataset or a plain iterable of LearningRow (via
        _stats_utils.rows_of)."""
        stats = compute_symbol_statistics(list(dataset.rows))
        assert len(stats) == 3

    def test_rows_with_no_symbol_are_skipped_not_a_none_bucket(self):
        class FakeRow:
            symbol = None
            pnl = 10.0

        stats = compute_symbol_statistics([FakeRow()])
        assert stats == []


# ══════════════════════════════════════════════════════════════════════════
# regime_statistics
# ══════════════════════════════════════════════════════════════════════════

class TestRegimeStatistics:

    def test_coverage_is_full_when_every_row_has_regime(self, dataset):
        result = compute_regime_statistics(dataset)
        assert result.coverage == 1.0
        assert result.rows_without_regime == 0

    def test_empty_dataset_coverage_is_none(self):
        result = compute_regime_statistics([])
        assert result.coverage is None

    def test_all_four_regimes_present(self, dataset):
        result = compute_regime_statistics(dataset)
        regimes = {b["regime"] for b in result.by_regime}
        assert regimes == {"TREND_UP", "TREND_DOWN", "HIGH_VOL", "RANGE"}

    def test_rows_without_regime_counted_honestly(self):
        class FakeRow:
            regime = None
            pnl = 5.0

        result = compute_regime_statistics([FakeRow(), FakeRow()])
        assert result.rows_without_regime == 2
        assert result.coverage == 0.0


# ══════════════════════════════════════════════════════════════════════════
# agent_statistics
# ══════════════════════════════════════════════════════════════════════════

class TestAgentStatistics:

    def test_empty_dataset_gives_empty_list(self):
        assert compute_agent_statistics([]) == []

    def test_agents_present_when_seeded_with_agents(self, dataset):
        stats = compute_agent_statistics(dataset)
        agents = {a.agent for a in stats}
        assert agents == {"smc", "regime", "ceo"}

    def test_no_agents_gives_empty_list(self, journal):
        seed_trades(journal, 5, with_agents=False)
        dataset = LearningDatasetBuilder(journal).build()
        assert compute_agent_statistics(dataset) == []

    def test_agreement_plus_disagreement_le_total(self, dataset):
        for a in compute_agent_statistics(dataset):
            assert a.agreement_count + a.disagreement_count <= a.total_trades

    def test_smc_always_agrees_since_seed_always_votes_long(self, dataset):
        """seed_trades() always has smc vote LONG and every trade's
        direction is LONG (see tests/_learning_helpers.py) -> smc
        should show 0 disagreement."""
        stats = {a.agent: a for a in compute_agent_statistics(dataset)}
        assert stats["smc"].disagreement_count == 0
        assert stats["smc"].agreement_count == stats["smc"].total_trades

    def test_sorted_by_win_rate_descending(self, dataset):
        stats = compute_agent_statistics(dataset)
        rates = [a.win_rate for a in stats]
        assert rates == sorted(rates, reverse=True)


# ══════════════════════════════════════════════════════════════════════════
# feature_statistics
# ══════════════════════════════════════════════════════════════════════════

class TestFeatureStatistics:

    def test_empty_dataset(self):
        result = compute_feature_statistics([])
        assert result.rows_considered == 0

    def test_mtf_aligned_buckets_present(self, dataset):
        result = compute_feature_statistics(dataset)
        assert "mtf_aligned" in result.by_feature
        assert "present" in result.by_feature["mtf_aligned"]
        assert "absent" in result.by_feature["mtf_aligned"]

    def test_bos_choch_fvg_ob_buckets_present(self, dataset):
        result = compute_feature_statistics(dataset)
        for flag in ("bos", "choch", "fvg", "ob"):
            assert flag in result.by_feature


# ══════════════════════════════════════════════════════════════════════════
# performance_tracker
# ══════════════════════════════════════════════════════════════════════════

class TestPerformanceTracker:

    def test_overall_stats_match_dataset_size(self, dataset):
        report = compute_performance_report(dataset)
        assert report.overall["total_trades"] == 30

    def test_class_wrapper_matches_function(self, dataset):
        via_class = PerformanceTracker().track(dataset)
        via_function = compute_performance_report(dataset)
        assert via_class.overall == via_function.overall

    def test_by_hour_covers_seeded_range(self, dataset):
        report = compute_performance_report(dataset)
        assert len(report.by_hour) > 0
        for stats in report.by_hour.values():
            assert stats["total_trades"] >= 1

    def test_by_weekday_totals_match_row_count(self, dataset):
        report = compute_performance_report(dataset)
        total = sum(s["total_trades"] for s in report.by_weekday.values())
        assert total == report.rows_with_timestamp

    def test_no_timestamp_counted_honestly(self):
        class FakeRow:
            timestamp = None
            pnl = 1.0
            running_drawdown = 0.0

        report = compute_performance_report([FakeRow(), FakeRow()])
        assert report.rows_without_timestamp == 2
        assert report.by_hour == {}

    def test_max_drawdown_is_non_positive(self, journal):
        seed_trades(journal, 20, win_rate=0.3)
        dataset = LearningDatasetBuilder(journal).build()
        report = compute_performance_report(dataset)
        assert report.max_drawdown <= 0

    def test_streaks_are_non_negative_integers(self, dataset):
        report = compute_performance_report(dataset)
        assert report.streaks["longest_winning_streak"] >= 0
        assert report.streaks["longest_losing_streak"] >= 0
