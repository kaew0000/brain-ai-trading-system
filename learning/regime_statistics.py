"""
learning/regime_statistics.py — V16 Phase 4C Step 1: per-regime
performance breakdown, one of pattern_miner.py's inputs ("best
regimes", "worst regimes").

Only real for legacy single-symbol trades today — see
dataset_builder.py's module docstring "Fields not yet populated".
`coverage` on RegimeStatistics reports what fraction of the dataset
actually had a regime recorded, so a consumer can see the gap rather
than silently trusting a breakdown built from a small, non-representative
subset.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ._stats_utils import rows_of, trade_stats


@dataclass(frozen=True)
class RegimeStatistics:
    by_regime:            list  # list[{"regime": str, "stats": dict}], sorted best-first
    rows_with_regime:      int
    rows_without_regime:    int
    coverage:              float | None  # rows_with_regime / total, None if dataset is empty


def compute_regime_statistics(dataset_or_rows) -> RegimeStatistics:
    rows = rows_of(dataset_or_rows)
    by_regime: dict[str, list] = defaultdict(list)
    without = 0
    for r in rows:
        if r.regime:
            by_regime[r.regime].append(r)
        else:
            without += 1

    breakdown = [{"regime": regime, "stats": trade_stats(rs)} for regime, rs in by_regime.items()]
    breakdown.sort(key=lambda x: x["stats"]["total_pnl"] if x["stats"]["total_pnl"] is not None else float("-inf"),
                    reverse=True)

    total = len(rows)
    with_regime = total - without
    return RegimeStatistics(
        by_regime=breakdown,
        rows_with_regime=with_regime,
        rows_without_regime=without,
        coverage=round(with_regime / total, 4) if total else None,
    )
