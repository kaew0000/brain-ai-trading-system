"""
learning/ — V16 Phase 4C Step 1: Autonomous Learning Pipeline
(Track A — Brain AI Trading System; see
docs/architecture/SEPARATION_POLICY.md, which lists "Ensemble
Learning" explicitly under Track A's Includes)

Pipeline:

    Trade Closed -> Journal -> Execution Attribution (Phase 4B, existing)
                                        |
                                        v
                      learning/dataset_builder.py  (LearningDatasetBuilder)
                                        |
                                        v
                      learning/performance_tracker.py,
                      learning/symbol_statistics.py,
                      learning/regime_statistics.py,
                      learning/agent_statistics.py,
                      learning/feature_statistics.py
                                        |
                                        v
                      learning/pattern_miner.py     (PatternMiner)
                                        |
                                        v
                      learning/recommendation_engine.py (RecommendationEngine)
                                        |
                                        v
                      learning/learning_snapshot.py  (LearningSnapshot)
                                        |
                                        v
                      learning/learning_report.py    (JSON reports)

Package-wide constraint — every module in this package is READ ONLY:

- Reads journal/journal_v2.py's existing get_ensemble_learning_dataset()
  (Phase 4B Step 2) — never queries the database directly, never adds
  a table, never writes a row.
- Never imports from execution/, portfolio/, risk/, or calls anything
  that places, modifies, or cancels an order.
- Never mutates CEOAgent.WEIGHTS, DYNAMIC_AGENT_WEIGHTS_ENABLED, or any
  other live trading-behavior setting.
- Produces recommendations as data (strings + structured facts) for a
  human to read — never a suggestion this package or anything importing
  it acts on automatically. "Learning only. Observation only.
  Recommendation only." — this phase's own brief.
"""
from __future__ import annotations

from .dataset_builder import LearningDataset, LearningDatasetBuilder, LearningRow
from .performance_tracker import PerformanceReport, PerformanceTracker
from .pattern_miner import Pattern, PatternMiner
from .recommendation_engine import Recommendation, RecommendationEngine
from .learning_snapshot import LearningSnapshot, build_learning_snapshot, save_snapshot
from .learning_report import LearningReportBundle, LearningReportGenerator
from .symbol_statistics import SymbolStatistics, compute_symbol_statistics
from .regime_statistics import RegimeStatistics, compute_regime_statistics
from .agent_statistics import AgentStatistics, compute_agent_statistics
from .feature_statistics import FeatureStatistics, compute_feature_statistics

__all__ = [
    "AgentStatistics",
    "FeatureStatistics",
    "LearningDataset",
    "LearningDatasetBuilder",
    "LearningReportBundle",
    "LearningReportGenerator",
    "LearningRow",
    "LearningSnapshot",
    "Pattern",
    "PatternMiner",
    "PerformanceReport",
    "PerformanceTracker",
    "Recommendation",
    "RecommendationEngine",
    "RegimeStatistics",
    "SymbolStatistics",
    "build_learning_snapshot",
    "compute_agent_statistics",
    "compute_feature_statistics",
    "compute_regime_statistics",
    "compute_symbol_statistics",
    "save_snapshot",
]
