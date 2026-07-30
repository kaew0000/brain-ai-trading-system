"""
learning/learning_report.py — V16 Phase 4C Step 1: top-level pipeline
orchestrator. Wires LearningDatasetBuilder -> PerformanceTracker +
PatternMiner -> RecommendationEngine -> LearningSnapshot together and
writes the four requested JSON reports:

    learning_report.json        — everything (dataset summary, patterns,
                                   recommendations, snapshot)
    performance_report.json     — learning/performance_tracker.py's
                                   PerformanceReport only
    pattern_report.json         — learning/pattern_miner.py's
                                   Pattern list only
    recommendation_report.json  — learning/recommendation_engine.py's
                                   Recommendation list only

This is the one module in learning/ that ties the whole pipeline
together end to end; every module it imports has already been
independently tested (see tests/test_learning_*.py) — this file's own
tests focus on the wiring and the JSON output shape, not re-testing
each stage's internals.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .dataset_builder import LearningDataset, LearningDatasetBuilder
from .learning_snapshot import LearningSnapshot, build_learning_snapshot
from .pattern_miner import DEFAULT_MIN_SAMPLE_SIZE, PatternMiner
from .performance_tracker import PerformanceReport, compute_performance_report
from .recommendation_engine import RecommendationEngine


@dataclass(frozen=True)
class LearningReportBundle:
    dataset:            LearningDataset
    performance:         PerformanceReport
    patterns:            list   # list[Pattern]
    recommendations:      list   # list[Recommendation]
    snapshot:            LearningSnapshot


class LearningReportGenerator:
    """Constructed with anything LearningDatasetBuilder accepts (in
    production a journal.journal_v2.TradeJournalV2 instance)."""

    def __init__(self, journal, min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE) -> None:
        self.dataset_builder = LearningDatasetBuilder(journal)
        self.pattern_miner = PatternMiner(min_sample_size=min_sample_size)
        self.recommendation_engine = RecommendationEngine()

    def generate(self, limit: int = 10_000, symbol: str | None = None) -> LearningReportBundle:
        dataset = self.dataset_builder.build(limit=limit, symbol=symbol)
        performance = compute_performance_report(dataset)
        patterns = self.pattern_miner.mine(dataset)
        recommendations = self.recommendation_engine.generate(patterns)
        snapshot = build_learning_snapshot(dataset, patterns, recommendations)
        return LearningReportBundle(
            dataset=dataset, performance=performance, patterns=patterns,
            recommendations=recommendations, snapshot=snapshot,
        )

    def write_reports(self, bundle: LearningReportBundle, directory: str | Path) -> dict:
        """Writes all four report files (overwriting any previous
        report of the SAME name — unlike learning_snapshot.py's
        timestamp-named files, these four are meant to be "the current
        report", not an accumulating history; the snapshot inside
        learning_report.json IS the timestamped historical record).
        Returns {"learning": path, "performance": path, "pattern": path,
        "recommendation": path}."""
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)

        paths = {}

        learning_path = directory / "learning_report.json"
        learning_path.write_text(json.dumps({
            "dataset_row_count": bundle.dataset.row_count,
            "dataset_source_params": bundle.dataset.source_params,
            "performance": asdict(bundle.performance),
            "patterns": [asdict(p) for p in bundle.patterns],
            "recommendations": [asdict(r) for r in bundle.recommendations],
            "snapshot": bundle.snapshot.to_dict(),
        }, indent=2, default=str))
        paths["learning"] = learning_path

        performance_path = directory / "performance_report.json"
        performance_path.write_text(json.dumps(asdict(bundle.performance), indent=2, default=str))
        paths["performance"] = performance_path

        pattern_path = directory / "pattern_report.json"
        pattern_path.write_text(json.dumps([asdict(p) for p in bundle.patterns], indent=2, default=str))
        paths["pattern"] = pattern_path

        recommendation_path = directory / "recommendation_report.json"
        recommendation_path.write_text(json.dumps([asdict(r) for r in bundle.recommendations], indent=2, default=str))
        paths["recommendation"] = recommendation_path

        return paths
