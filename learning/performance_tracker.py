"""
learning/performance_tracker.py — V16 Phase 4C Step 1: aggregate
performance numbers over a LearningDataset — overall stats, streaks,
drawdown summary, hour-of-day and weekday breakdowns. The raw
measurements pattern_miner.py turns into flagged Pattern objects; this
module itself makes no judgment about what's "good" or "bad", it only
counts and averages.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from ._stats_utils import rows_of, streaks, trade_stats


@dataclass(frozen=True)
class PerformanceReport:
    overall:                dict   # trade_stats() over the whole dataset
    streaks:                 dict   # {"longest_winning_streak":, "longest_losing_streak":}
    max_drawdown:             float | None   # most negative running_drawdown seen (0.0 or negative)
    by_hour:                  dict   # {0..23: trade_stats()}, only hours with >=1 trade
    by_weekday:                dict   # {"Monday".."Sunday": trade_stats()}, only days with >=1 trade
    rows_with_timestamp:       int
    rows_without_timestamp:     int


def _parse_hour_weekday(timestamp: str | None):
    if not timestamp:
        return None, None
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None, None
    return dt.hour, dt.strftime("%A")


def compute_performance_report(dataset_or_rows) -> PerformanceReport:
    rows = list(rows_of(dataset_or_rows))

    by_hour_rows: dict[int, list] = defaultdict(list)
    by_weekday_rows: dict[str, list] = defaultdict(list)
    without_ts = 0
    for r in rows:
        hour, weekday = _parse_hour_weekday(r.timestamp)
        if hour is None:
            without_ts += 1
            continue
        by_hour_rows[hour].append(r)
        by_weekday_rows[weekday].append(r)

    drawdowns = [r.running_drawdown for r in rows if r.running_drawdown is not None]

    return PerformanceReport(
        overall=trade_stats(rows),
        streaks=streaks(rows),
        max_drawdown=round(min(drawdowns), 4) if drawdowns else None,
        by_hour={h: trade_stats(rs) for h, rs in sorted(by_hour_rows.items())},
        by_weekday={d: trade_stats(rs) for d, rs in by_weekday_rows.items()},
        rows_with_timestamp=len(rows) - without_ts,
        rows_without_timestamp=without_ts,
    )


class PerformanceTracker:
    """Thin, stateless entry point matching this package's convention
    (learning/pattern_miner.py's PatternMiner, learning/recommendation_engine.py's
    RecommendationEngine) — kept as a class so a caller wiring the whole
    pipeline together treats every stage the same way, even though this
    one has no configuration of its own."""

    def track(self, dataset_or_rows) -> PerformanceReport:
        return compute_performance_report(dataset_or_rows)
