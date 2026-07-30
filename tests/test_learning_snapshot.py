"""
tests/test_learning_snapshot.py — V16 Phase 4C Step 1
"""
from __future__ import annotations

import json

import pytest

from journal.journal_v2 import TradeJournalV2
from learning.dataset_builder import LearningDatasetBuilder
from learning.learning_snapshot import LearningSnapshot, build_learning_snapshot, save_snapshot
from learning.pattern_miner import PatternMiner
from learning.recommendation_engine import RecommendationEngine
from tests._learning_helpers import seed_trades

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


def _build_snapshot(journal, n=40, min_sample_size=5):
    seed_trades(journal, n)
    dataset = LearningDatasetBuilder(journal).build()
    patterns = PatternMiner(min_sample_size=min_sample_size).mine(dataset)
    recommendations = RecommendationEngine().generate(patterns)
    return build_learning_snapshot(dataset, patterns, recommendations)


class TestBuildLearningSnapshot:

    def test_returns_learning_snapshot_instance(self, journal):
        snap = _build_snapshot(journal)
        assert isinstance(snap, LearningSnapshot)

    def test_is_frozen(self, journal):
        snap = _build_snapshot(journal)
        with pytest.raises(Exception):
            snap.timestamp = "x"

    def test_dataset_row_count_matches(self, journal):
        snap = _build_snapshot(journal, n=25)
        assert snap.dataset_row_count == 25

    def test_statistics_has_all_four_dimensions(self, journal):
        snap = _build_snapshot(journal)
        assert set(snap.statistics.keys()) == {"symbol", "regime", "agent", "feature", "performance"}

    def test_patterns_and_recommendations_are_dicts(self, journal):
        snap = _build_snapshot(journal, n=60, min_sample_size=5)
        assert len(snap.patterns) > 0
        assert all(isinstance(p, dict) for p in snap.patterns)
        assert all(isinstance(r, dict) for r in snap.recommendations)

    def test_empty_dataset_still_produces_a_valid_snapshot(self, journal):
        dataset = LearningDatasetBuilder(journal).build()
        patterns = PatternMiner().mine(dataset)
        recs = RecommendationEngine().generate(patterns)
        snap = build_learning_snapshot(dataset, patterns, recs)
        assert snap.dataset_row_count == 0
        assert snap.patterns == []


class TestSerialization:

    def test_to_dict_is_a_plain_dict(self, journal):
        snap = _build_snapshot(journal)
        d = snap.to_dict()
        assert isinstance(d, dict)
        assert d["dataset_row_count"] == snap.dataset_row_count

    def test_to_json_round_trips(self, journal):
        snap = _build_snapshot(journal)
        parsed = json.loads(snap.to_json())
        assert parsed["schema_version"] == snap.schema_version
        assert parsed["dataset_row_count"] == snap.dataset_row_count


class TestSaveSnapshot:

    def test_writes_a_file(self, journal, tmp_path):
        snap = _build_snapshot(journal)
        out_dir = tmp_path / "snapshots"
        path = save_snapshot(snap, out_dir)
        assert path.exists()
        assert path.name.startswith("learning_snapshot_")
        assert path.suffix == ".json"

    def test_written_file_is_valid_json(self, journal, tmp_path):
        snap = _build_snapshot(journal)
        path = save_snapshot(snap, tmp_path / "snapshots")
        with open(path) as f:
            data = json.load(f)
        assert data["dataset_row_count"] == snap.dataset_row_count

    def test_two_snapshots_do_not_overwrite_each_other(self, journal, tmp_path):
        import time
        snap1 = _build_snapshot(journal, n=5)
        time.sleep(0.01)
        snap2 = _build_snapshot(journal, n=10)
        out_dir = tmp_path / "snapshots"
        path1 = save_snapshot(snap1, out_dir)
        path2 = save_snapshot(snap2, out_dir)
        assert path1 != path2
        assert path1.exists() and path2.exists()

    def test_creates_directory_if_missing(self, journal, tmp_path):
        snap = _build_snapshot(journal)
        out_dir = tmp_path / "does" / "not" / "exist" / "yet"
        path = save_snapshot(snap, out_dir)
        assert path.exists()
