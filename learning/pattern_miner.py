"""
learning/pattern_miner.py — V16 Phase 4C Step 1: detects notable
patterns across a LearningDataset. Read-only analysis — a Pattern is a
fact plus a severity label, never an instruction and never anything
this module or its caller acts on automatically ("Do NOT change
anything automatically" — this phase's own PATTERN MINER brief).

Every pattern below is gated by `min_sample_size` (default 5) so a
single lucky/unlucky trade can't produce a "pattern" — see this
module's own tests for what happens at n=1..4 (nothing is reported,
not a low-confidence pattern anyway).
"""
from __future__ import annotations

from dataclasses import dataclass

from ._stats_utils import rows_of
from .agent_statistics import compute_agent_statistics
from .performance_tracker import compute_performance_report
from .regime_statistics import compute_regime_statistics
from .symbol_statistics import compute_symbol_statistics

DEFAULT_MIN_SAMPLE_SIZE = 5
_CONFIDENCE_BUCKETS = [(0, 20), (20, 40), (40, 60), (60, 80), (80, 100)]


@dataclass(frozen=True)
class Pattern:
    kind:         str    # e.g. "best_symbol", "worst_symbol", "best_regime", "worst_regime",
                          # "confidence_range", "best_hour", "worst_hour", "best_weekday",
                          # "worst_weekday", "winning_streak", "losing_streak",
                          # "agent_agreement_quality", "agent_disagreement_quality"
    subject:       str    # e.g. "BTCUSDT", "HIGH_VOL", "14:00", "Monday", "SMC_ANALYST"
    metric:        dict   # supporting numbers — win_rate, total_pnl, sample_size, etc.
    description:    str    # human-readable one-liner
    severity:       str    # "positive" | "negative" | "neutral"


def _best_worst(entries, key_fn, min_sample_size, sample_size_fn, kind_prefix, subject_fn, describe_fn):
    """Shared best/worst-of-N helper — every *_statistics module's
    output shape differs slightly, so this takes small accessor
    functions rather than assuming a common dataclass shape."""
    eligible = [e for e in entries if sample_size_fn(e) >= min_sample_size and key_fn(e) is not None]
    if not eligible:
        return []
    eligible.sort(key=key_fn, reverse=True)
    best, worst = eligible[0], eligible[-1]
    patterns = []
    if key_fn(best) is not None:
        patterns.append(Pattern(kind=f"best_{kind_prefix}", subject=subject_fn(best),
                                 metric={"win_rate": key_fn(best), "sample_size": sample_size_fn(best)},
                                 description=describe_fn(best, "best"), severity="positive"))
    if len(eligible) > 1 and worst is not best:
        patterns.append(Pattern(kind=f"worst_{kind_prefix}", subject=subject_fn(worst),
                                 metric={"win_rate": key_fn(worst), "sample_size": sample_size_fn(worst)},
                                 description=describe_fn(worst, "worst"), severity="negative"))
    return patterns


class PatternMiner:

    def __init__(self, min_sample_size: int = DEFAULT_MIN_SAMPLE_SIZE) -> None:
        self.min_sample_size = min_sample_size

    def mine(self, dataset_or_rows) -> list[Pattern]:
        rows = list(rows_of(dataset_or_rows))
        patterns: list[Pattern] = []
        patterns += self._symbol_patterns(rows)
        patterns += self._regime_patterns(rows)
        patterns += self._symbol_regime_patterns(rows)
        patterns += self._confidence_range_patterns(rows)
        patterns += self._time_patterns(rows)
        patterns += self._streak_patterns(rows)
        patterns += self._agent_patterns(rows)
        patterns += self._trend_patterns(rows)
        return patterns

    # ── individual dimensions ───────────────────────────────────────────

    def _symbol_patterns(self, rows) -> list[Pattern]:
        stats = compute_symbol_statistics(rows)
        return _best_worst(
            stats, key_fn=lambda s: s.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda s: s.stats["trades_with_pnl"], kind_prefix="symbol",
            subject_fn=lambda s: s.symbol,
            describe_fn=lambda s, which: f"{s.symbol} is the {which}-performing symbol "
                                          f"(win rate {s.stats['win_rate']:.0%}, n={s.stats['trades_with_pnl']}).",
        )

    def _regime_patterns(self, rows) -> list[Pattern]:
        regime_stats = compute_regime_statistics(rows)
        entries = [type("E", (), {"regime": e["regime"], "stats": e["stats"]}) for e in regime_stats.by_regime]
        return _best_worst(
            entries, key_fn=lambda e: e.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda e: e.stats["trades_with_pnl"], kind_prefix="regime",
            subject_fn=lambda e: e.regime,
            describe_fn=lambda e, which: f"{e.regime} is the {which}-performing regime "
                                          f"(win rate {e.stats['win_rate']:.0%}, n={e.stats['trades_with_pnl']}).",
        )

    def _confidence_range_patterns(self, rows) -> list[Pattern]:
        from ._stats_utils import trade_stats
        buckets = []
        for lo, hi in _CONFIDENCE_BUCKETS:
            in_range = [r for r in rows
                        if (r.signal_confidence if r.signal_confidence is not None else r.close_confidence) is not None
                        and lo <= (r.signal_confidence if r.signal_confidence is not None else r.close_confidence) < hi]
            stats = trade_stats(in_range)
            buckets.append({"label": f"{lo}-{hi}", "stats": stats})
        entries = [type("E", (), {"label": b["label"], "stats": b["stats"]}) for b in buckets]
        return _best_worst(
            entries, key_fn=lambda e: e.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda e: e.stats["trades_with_pnl"], kind_prefix="confidence_range",
            subject_fn=lambda e: e.label,
            describe_fn=lambda e, which: f"Confidence range {e.label} is the {which}-performing "
                                          f"(win rate {e.stats['win_rate']:.0%}, n={e.stats['trades_with_pnl']}).",
        )

    def _time_patterns(self, rows) -> list[Pattern]:
        perf = compute_performance_report(rows)
        patterns = []

        hour_entries = [type("E", (), {"label": f"{h:02d}:00", "stats": s}) for h, s in perf.by_hour.items()]
        patterns += _best_worst(
            hour_entries, key_fn=lambda e: e.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda e: e.stats["trades_with_pnl"], kind_prefix="hour",
            subject_fn=lambda e: e.label,
            describe_fn=lambda e, which: f"{e.label} UTC is the {which}-performing hour "
                                          f"(win rate {e.stats['win_rate']:.0%}, n={e.stats['trades_with_pnl']}).",
        )

        weekday_entries = [type("E", (), {"label": d, "stats": s}) for d, s in perf.by_weekday.items()]
        patterns += _best_worst(
            weekday_entries, key_fn=lambda e: e.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda e: e.stats["trades_with_pnl"], kind_prefix="weekday",
            subject_fn=lambda e: e.label,
            describe_fn=lambda e, which: f"{e.label} is the {which}-performing weekday "
                                          f"(win rate {e.stats['win_rate']:.0%}, n={e.stats['trades_with_pnl']}).",
        )
        return patterns

    def _streak_patterns(self, rows) -> list[Pattern]:
        perf = compute_performance_report(rows)
        patterns = []
        if perf.streaks["longest_winning_streak"] >= self.min_sample_size:
            n = perf.streaks["longest_winning_streak"]
            patterns.append(Pattern(kind="winning_streak", subject="sequence", metric={"length": n},
                                     description=f"Longest winning streak observed: {n} trades in a row.",
                                     severity="positive"))
        if perf.streaks["longest_losing_streak"] >= self.min_sample_size:
            n = perf.streaks["longest_losing_streak"]
            patterns.append(Pattern(kind="losing_streak", subject="sequence", metric={"length": n},
                                     description=f"Longest losing streak observed: {n} trades in a row.",
                                     severity="negative"))
        return patterns

    def _agent_patterns(self, rows) -> list[Pattern]:
        patterns = []
        for a in compute_agent_statistics(rows):
            agree_n = a.agreement_count
            disagree_n = a.disagreement_count
            if agree_n >= self.min_sample_size and a.agreement_win_rate is not None:
                patterns.append(Pattern(
                    kind="agent_agreement_quality", subject=a.agent,
                    metric={"win_rate": a.agreement_win_rate, "sample_size": agree_n},
                    description=f"{a.agent}'s vote agreed with the trade direction in {agree_n} trades, "
                                f"win rate {a.agreement_win_rate:.0%} when it agreed.",
                    severity="positive" if a.agreement_win_rate >= 0.5 else "negative",
                ))
            if disagree_n >= self.min_sample_size and a.disagreement_win_rate is not None:
                patterns.append(Pattern(
                    kind="agent_disagreement_quality", subject=a.agent,
                    metric={"win_rate": a.disagreement_win_rate, "sample_size": disagree_n},
                    description=f"{a.agent}'s vote disagreed with the trade direction in {disagree_n} trades, "
                                f"win rate {a.disagreement_win_rate:.0%} when it disagreed.",
                    severity="negative" if a.disagreement_win_rate >= 0.5 else "neutral",
                ))
        return patterns

    def _symbol_regime_patterns(self, rows) -> list[Pattern]:
        """The joint (symbol, regime) breakdown grounding a recommendation
        like "SYMBOL performs poorly during REGIME regime" in a real,
        computed correlation — not two independent best/worst patterns
        glued together by the recommendation engine, which would risk
        implying a joint correlation that was never actually measured."""
        from collections import defaultdict

        from ._stats_utils import trade_stats

        by_combo: dict[tuple, list] = defaultdict(list)
        for r in rows:
            if r.symbol and r.regime:
                by_combo[(r.symbol, r.regime)].append(r)

        entries = [
            type("E", (), {"symbol": sym, "regime": reg, "stats": trade_stats(rs)})
            for (sym, reg), rs in by_combo.items()
        ]
        return _best_worst(
            entries, key_fn=lambda e: e.stats["win_rate"], min_sample_size=self.min_sample_size,
            sample_size_fn=lambda e: e.stats["trades_with_pnl"], kind_prefix="symbol_regime_combo",
            subject_fn=lambda e: f"{e.symbol}/{e.regime}",
            describe_fn=lambda e, which: f"{e.symbol} performs {'well' if which == 'best' else 'poorly'} "
                                          f"during {e.regime} regime (win rate {e.stats['win_rate']:.0%}, "
                                          f"n={e.stats['trades_with_pnl']}).",
        )

    def _trend_patterns(self, rows) -> list[Pattern]:
        """Splits the (chronologically-sorted) dataset in half and
        compares avg latency, avg slippage, and a simple risk-adjusted-
        return measure (avg pnl per trade) between the two halves — a
        real first-half-vs-second-half comparison, not a guess. Needs
        2x min_sample_size total (min_sample_size per half) to report
        anything."""
        n = len(rows)
        half = n // 2
        if half < self.min_sample_size:
            return []
        first, second = rows[:half], rows[half:]
        patterns = []

        def _avg(vals):
            vals = [v for v in vals if v is not None]
            return (sum(vals) / len(vals)) if vals else None

        lat1, lat2 = _avg([r.latency_seconds for r in first]), _avg([r.latency_seconds for r in second])
        if lat1 is not None and lat2 is not None and lat1 > 0:
            change = (lat2 - lat1) / lat1
            if abs(change) >= 0.10:  # 10%+ move — small noise doesn't get reported as a "trend"
                direction = "increased" if change > 0 else "decreased"
                patterns.append(Pattern(
                    kind="latency_trend", subject="execution_latency",
                    metric={"first_half_avg": round(lat1, 4), "second_half_avg": round(lat2, 4), "change_pct": round(change, 4)},
                    description=f"Execution latency {direction} ({lat1:.3f}s -> {lat2:.3f}s, "
                                f"{change:+.0%}) comparing the first and second half of this dataset.",
                    severity="negative" if change > 0 else "positive",
                ))

        rar1, rar2 = _avg([r.pnl for r in first]), _avg([r.pnl for r in second])
        if rar1 is not None and rar2 is not None and rar1 != 0:
            change = (rar2 - rar1) / abs(rar1)
            if abs(change) >= 0.10:
                direction = "increased" if change > 0 else "decreased"
                patterns.append(Pattern(
                    kind="risk_adjusted_return_trend", subject="avg_pnl_per_trade",
                    metric={"first_half_avg": round(rar1, 4), "second_half_avg": round(rar2, 4), "change_pct": round(change, 4)},
                    description=f"Average PnL per trade {direction} ({rar1:.2f} -> {rar2:.2f}, {change:+.0%}) "
                                f"comparing the first and second half of this dataset.",
                    severity="positive" if change > 0 else "negative",
                ))

        return patterns
