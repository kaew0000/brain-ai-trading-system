"""
learning/learning_snapshot.py — V16 Phase 4C Step 1: an immutable,
point-in-time bundle of everything the pipeline learned from one
LearningDataset — the "SNAPSHOT" deliverable.

A snapshot is a frozen dataclass (Python-level immutability) plus a
JSON serialization that never gets edited in place — each call to
build_learning_snapshot() + save_snapshot() writes a NEW,
timestamp-named file (learning_snapshot_<ISO-timestamp>.json), never
overwrites a previous one. This is a plain JSON file on disk, not a
new database layer or table — consistent with this phase's "Do not
invent another database layer" instruction (from Phase 4B Step 2's own
brief, which this phase's constraints echo for the journal specifically;
applied here to snapshots too, for the same reason: one more ad-hoc
persistence mechanism is exactly what "no duplicate modules" warns
against).
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from .agent_statistics import compute_agent_statistics
from .dataset_builder import LearningDataset
from .feature_statistics import compute_feature_statistics
from .pattern_miner import Pattern
from .performance_tracker import compute_performance_report
from .recommendation_engine import Recommendation
from .regime_statistics import compute_regime_statistics
from .symbol_statistics import compute_symbol_statistics

SNAPSHOT_SCHEMA_VERSION = "4c-step1.0"


@dataclass(frozen=True)
class LearningSnapshot:
    timestamp:             str
    schema_version:         str
    dataset_version:         str
    dataset_row_count:       int
    dataset_source_params:    dict
    summary:                dict   # overall performance numbers
    statistics:              dict   # {"symbol":, "regime":, "agent":, "feature":, "performance":}
    patterns:                list   # list[dict] — every Pattern found, asdict'd
    recommendations:          list   # list[dict] — every Recommendation, asdict'd

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)


def build_learning_snapshot(
    dataset: LearningDataset,
    patterns: list[Pattern],
    recommendations: list[Recommendation],
) -> LearningSnapshot:
    """Pure function: same dataset + patterns + recommendations in ->
    same snapshot out, nothing read from disk or the journal here — the
    caller (learning_report.py, or a future scheduled job) is
    responsible for having already run LearningDatasetBuilder,
    PatternMiner, and RecommendationEngine."""
    performance = compute_performance_report(dataset)
    return LearningSnapshot(
        timestamp=datetime.now(timezone.utc).isoformat(),
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        dataset_version=dataset.schema_version,
        dataset_row_count=dataset.row_count,
        dataset_source_params=dataset.source_params,
        summary=performance.overall,
        statistics={
            "symbol":  [asdict(s) for s in compute_symbol_statistics(dataset)],
            "regime":  asdict(compute_regime_statistics(dataset)),
            "agent":   [asdict(a) for a in compute_agent_statistics(dataset)],
            "feature": asdict(compute_feature_statistics(dataset)),
            "performance": asdict(performance),
        },
        patterns=[asdict(p) for p in patterns],
        recommendations=[asdict(r) for r in recommendations],
    )


def save_snapshot(snapshot: LearningSnapshot, directory: str | Path) -> Path:
    """Writes learning_snapshot_<timestamp>.json — never overwrites an
    existing file (the timestamp in the filename is the snapshot's own
    `.timestamp`, colon-safe for a filename). Creates `directory` if it
    doesn't exist. Returns the written path. Never silently swallows a
    write failure — unlike the rest of this READ-ONLY package, writing
    a snapshot file (not a journal/database write) is this module's one
    legitimate side effect, so a failure here should be visible to the
    caller, not logged-and-ignored."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    safe_ts = snapshot.timestamp.replace(":", "-")
    path = directory / f"learning_snapshot_{safe_ts}.json"
    path.write_text(snapshot.to_json())
    return path
