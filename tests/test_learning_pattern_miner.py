"""
tests/test_learning_pattern_miner.py — V16 Phase 4C Step 1
"""
from __future__ import annotations

import pytest

from journal.journal_v2 import TradeJournalV2
from learning.dataset_builder import LearningDatasetBuilder
from learning.pattern_miner import Pattern, PatternMiner
from tests._learning_helpers import seed_trades

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


class TestSampleSizeGating:

    def test_empty_dataset_yields_no_patterns(self):
        assert PatternMiner(min_sample_size=5).mine([]) == []

    def test_below_min_sample_size_yields_no_patterns(self, journal):
        seed_trades(journal, 3)  # below default min_sample_size=5, and 1 symbol/regime bucket each has <5
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=10).mine(dataset)
        assert patterns == []

    def test_never_raises_on_malformed_rows(self):
        class FakeRow:
            symbol = None
            regime = None
            signal_confidence = None
            close_confidence = None
            mtf_aligned = None
            smc_flags = {}
            direction = None
            result = None
            pnl = None
            latency_seconds = None
            timestamp = None
            agent_participation = []
            running_drawdown = None

        # Should not raise even with a pile of Nones
        PatternMiner(min_sample_size=1).mine([FakeRow() for _ in range(10)])


class TestPatternsAreReal:

    def test_patterns_found_with_enough_data(self, journal):
        seed_trades(journal, 60)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        assert len(patterns) > 0
        assert all(isinstance(p, Pattern) for p in patterns)

    def test_best_symbol_pattern_has_real_metric(self, journal):
        seed_trades(journal, 60)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        best_symbol = [p for p in patterns if p.kind == "best_symbol"]
        assert len(best_symbol) == 1
        assert 0.0 <= best_symbol[0].metric["win_rate"] <= 1.0
        assert best_symbol[0].metric["sample_size"] >= 5

    def test_severity_matches_kind(self, journal):
        seed_trades(journal, 60)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        for p in patterns:
            if p.kind.startswith("best_"):
                assert p.severity == "positive"
            if p.kind.startswith("worst_"):
                assert p.severity == "negative"

    def test_symbol_regime_combo_pattern_present_with_enough_data(self, journal):
        seed_trades(journal, 80)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        combos = [p for p in patterns if "symbol_regime_combo" in p.kind]
        # Not guaranteed non-empty for every seed, but the subject shape must be right if present
        for p in combos:
            assert "/" in p.subject


class TestStreakPatterns:

    def test_losing_streak_pattern_when_present(self, journal):
        seed_trades(journal, 30, win_rate=0.1)  # mostly losses -> long losing streak likely
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=3).mine(dataset)
        losing = [p for p in patterns if p.kind == "losing_streak"]
        if losing:
            assert losing[0].metric["length"] >= 3
            assert losing[0].severity == "negative"

    def test_winning_streak_pattern_when_present(self, journal):
        seed_trades(journal, 30, win_rate=0.95)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=3).mine(dataset)
        winning = [p for p in patterns if p.kind == "winning_streak"]
        if winning:
            assert winning[0].severity == "positive"


class TestAgentPatterns:

    def test_agent_agreement_pattern_present(self, journal):
        seed_trades(journal, 60, with_agents=True)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        agreement = [p for p in patterns if p.kind == "agent_agreement_quality"]
        assert len(agreement) > 0

    def test_no_agents_gives_no_agent_patterns(self, journal):
        seed_trades(journal, 30, with_agents=False)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=3).mine(dataset)
        assert not any(p.kind.startswith("agent_") for p in patterns)


class TestTrendPatterns:

    def test_no_trend_patterns_below_double_min_sample_size(self, journal):
        seed_trades(journal, 8)  # half=4, below default min_sample_size=5
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        assert not any("trend" in p.kind for p in patterns)

    def test_trend_pattern_metric_shape_when_present(self, journal):
        seed_trades(journal, 40)
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner(min_sample_size=5).mine(dataset)
        trends = [p for p in patterns if "trend" in p.kind]
        for p in trends:
            assert "first_half_avg" in p.metric
            assert "second_half_avg" in p.metric
            assert "change_pct" in p.metric
