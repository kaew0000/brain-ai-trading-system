"""
learning/feature_statistics.py — V16 Phase 4C Step 1: win-rate
breakdown by the structural feature flags actually present in
today's dataset (smc_flags' bos/choch/fvg/ob, and mtf_aligned) — the
only per-trade "features" journal/journal_v2.py's trades table
currently stores (see dataset_builder.py's module docstring; real for
legacy single-symbol trades, absent for V16 multi-symbol trades).

Not a general feature-engineering module — it reports on the specific
boolean flags already in the dataset, nothing invented or derived from
raw OHLCV (that's research/feature_store.py's job, a different,
pre-existing module this phase does not duplicate or replace).
"""
from __future__ import annotations

from dataclasses import dataclass

from ._stats_utils import rows_of, trade_stats


@dataclass(frozen=True)
class FeatureStatistics:
    by_feature:  dict  # {"bos": {"present": {...trade_stats}, "absent": {...trade_stats}}, ...}
    rows_considered: int


_FLAG_FIELDS = ("bos", "choch", "fvg", "ob")


def compute_feature_statistics(dataset_or_rows) -> FeatureStatistics:
    rows = list(rows_of(dataset_or_rows))

    by_feature: dict[str, dict] = {}
    for flag in _FLAG_FIELDS:
        present = [r for r in rows if (r.smc_flags or {}).get(flag)]
        absent = [r for r in rows if r.smc_flags is not None and flag in (r.smc_flags or {}) and not r.smc_flags.get(flag)]
        by_feature[flag] = {"present": trade_stats(present), "absent": trade_stats(absent)}

    mtf_true = [r for r in rows if r.mtf_aligned is True]
    mtf_false = [r for r in rows if r.mtf_aligned is False]
    by_feature["mtf_aligned"] = {"present": trade_stats(mtf_true), "absent": trade_stats(mtf_false)}

    return FeatureStatistics(by_feature=by_feature, rows_considered=len(rows))
