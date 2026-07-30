"""
tests/test_learning_report.py — V16 Phase 4C Step 1: LearningReportGenerator
wiring + the four JSON report files.
"""
from __future__ import annotations

import json

import pytest

from journal.journal_v2 import TradeJournalV2
from learning.learning_report import LearningReportBundle, LearningReportGenerator
from tests._learning_helpers import seed_trades

pytestmark = pytest.mark.unit


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "test.db"))


class TestGenerate:

    def test_returns_a_bundle(self, journal):
        seed_trades(journal, 20)
        bundle = LearningReportGenerator(journal, min_sample_size=5).generate()
        assert isinstance(bundle, LearningReportBundle)

    def test_bundle_pieces_are_internally_consistent(self, journal):
        seed_trades(journal, 60)
        bundle = LearningReportGenerator(journal, min_sample_size=5).generate()
        assert bundle.dataset.row_count == 60
        assert bundle.performance.overall["total_trades"] == 60
        assert bundle.snapshot.dataset_row_count == 60

    def test_empty_journal_produces_a_valid_empty_bundle(self, journal):
        bundle = LearningReportGenerator(journal).generate()
        assert bundle.dataset.row_count == 0
        assert bundle.patterns == []
        assert bundle.recommendations == []

    def test_symbol_and_limit_forwarded_to_dataset_builder(self, journal):
        seed_trades(journal, 9)
        bundle = LearningReportGenerator(journal).generate(symbol="ETHUSDT")
        assert bundle.dataset.row_count == 3
        assert all(r.symbol == "ETHUSDT" for r in bundle.dataset.rows)

    def test_min_sample_size_forwarded_to_pattern_miner(self, journal):
        seed_trades(journal, 8)
        loose = LearningReportGenerator(journal, min_sample_size=3).generate()
        strict = LearningReportGenerator(journal, min_sample_size=100).generate()
        assert len(strict.patterns) == 0
        assert len(loose.patterns) >= len(strict.patterns)


class TestWriteReports:

    def test_writes_all_four_files(self, journal, tmp_path):
        seed_trades(journal, 30)
        gen = LearningReportGenerator(journal, min_sample_size=5)
        bundle = gen.generate()
        paths = gen.write_reports(bundle, tmp_path)
        assert set(paths.keys()) == {"learning", "performance", "pattern", "recommendation"}
        for p in paths.values():
            assert p.exists()

    def test_file_names_match_the_brief(self, journal, tmp_path):
        seed_trades(journal, 10)
        gen = LearningReportGenerator(journal)
        paths = gen.write_reports(gen.generate(), tmp_path)
        assert paths["learning"].name == "learning_report.json"
        assert paths["performance"].name == "performance_report.json"
        assert paths["pattern"].name == "pattern_report.json"
        assert paths["recommendation"].name == "recommendation_report.json"

    def test_all_four_files_are_valid_json(self, journal, tmp_path):
        seed_trades(journal, 30)
        gen = LearningReportGenerator(journal, min_sample_size=5)
        paths = gen.write_reports(gen.generate(), tmp_path)
        for path in paths.values():
            with open(path) as f:
                json.load(f)  # raises if not valid JSON

    def test_learning_report_contains_everything(self, journal, tmp_path):
        seed_trades(journal, 60)
        gen = LearningReportGenerator(journal, min_sample_size=5)
        paths = gen.write_reports(gen.generate(), tmp_path)
        with open(paths["learning"]) as f:
            data = json.load(f)
        assert set(data.keys()) == {
            "dataset_row_count", "dataset_source_params", "performance",
            "patterns", "recommendations", "snapshot",
        }

    def test_pattern_report_is_a_flat_list(self, journal, tmp_path):
        seed_trades(journal, 60)
        gen = LearningReportGenerator(journal, min_sample_size=5)
        paths = gen.write_reports(gen.generate(), tmp_path)
        with open(paths["pattern"]) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_recommendation_report_is_a_flat_list(self, journal, tmp_path):
        seed_trades(journal, 60)
        gen = LearningReportGenerator(journal, min_sample_size=5)
        paths = gen.write_reports(gen.generate(), tmp_path)
        with open(paths["recommendation"]) as f:
            data = json.load(f)
        assert isinstance(data, list)

    def test_rerunning_overwrites_the_same_four_files(self, journal, tmp_path):
        seed_trades(journal, 10)
        gen = LearningReportGenerator(journal)
        paths1 = gen.write_reports(gen.generate(), tmp_path)
        seed_trades(journal, 10, seed=999)  # more trades added
        paths2 = gen.write_reports(gen.generate(), tmp_path)
        assert paths1 == paths2  # same filenames — "the current report", not an accumulating history
        with open(paths2["learning"]) as f:
            data = json.load(f)
        assert data["dataset_row_count"] == 20  # reflects the second, larger generate()


class TestNeverRaisesOnBrokenJournal:

    def test_generate_does_not_raise(self):
        class BrokenJournal:
            def get_ensemble_learning_dataset(self, **kwargs):
                raise RuntimeError("db exploded")

        bundle = LearningReportGenerator(BrokenJournal()).generate()
        assert bundle.dataset.row_count == 0
