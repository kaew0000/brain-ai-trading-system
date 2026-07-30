"""
learning/_stats_utils.py — shared aggregate-stat helpers, private to
the learning/ package (leading underscore: not exported from
learning/__init__.py, not part of the public API). Exists purely so
symbol_statistics.py, regime_statistics.py, performance_tracker.py, and
pattern_miner.py don't each reimplement the same win-rate/profit-
factor/avg-pnl arithmetic — "No duplicated logic" (this phase's own
Quality requirement).
"""
from __future__ import annotations


def rows_of(dataset_or_rows):
    """Accept either a learning.dataset_builder.LearningDataset or a
    plain iterable of LearningRow — every public function in this
    package accepts both, so a caller who already has the .rows tuple
    doesn't need to re-wrap it."""
    if hasattr(dataset_or_rows, "rows"):
        return dataset_or_rows.rows
    return tuple(dataset_or_rows)


def trade_stats(rows) -> dict:
    """rows: iterable of LearningRow. wins/losses are counted from
    `.pnl` sign, not `.result`, so this stays correct even for a
    hypothetical future `result` value beyond WIN/LOSS — but note
    total_trades counts ALL rows passed in (including ones with no pnl
    yet, e.g. a still-open or unresolved trade slipping through),
    while every pnl-based stat below only considers rows that actually
    have a pnl. profit_factor is None (never `inf`) when there are no
    losing trades in the set — an undefined ratio, not fabricated as
    infinity (keeps every report JSON-serializable without special
    casing)."""
    rows = list(rows)
    total = len(rows)
    pnls = [r.pnl for r in rows if r.pnl is not None]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    return {
        "total_trades":     total,
        "trades_with_pnl":  len(pnls),
        "wins":             len(wins),
        "losses":           len(losses),
        "win_rate":         round(len(wins) / len(pnls), 4) if pnls else None,
        "total_pnl":        round(sum(pnls), 4) if pnls else None,
        "avg_pnl":          round(sum(pnls) / len(pnls), 4) if pnls else None,
        "profit_factor":    round(gross_profit / gross_loss, 4) if gross_loss > 0 else None,
        "best_pnl":         round(max(pnls), 4) if pnls else None,
        "worst_pnl":        round(min(pnls), 4) if pnls else None,
    }


def streaks(rows) -> dict:
    """Longest winning/losing streak by pnl sign, in the order `rows`
    is given (caller's responsibility to pass chronological order —
    LearningDataset.rows already is, via dataset_builder.py's sort)."""
    longest_win = longest_loss = current_win = current_loss = 0
    for r in rows:
        if r.pnl is None:
            continue
        if r.pnl > 0:
            current_win += 1
            current_loss = 0
        elif r.pnl < 0:
            current_loss += 1
            current_win = 0
        else:
            current_win = current_loss = 0
        longest_win = max(longest_win, current_win)
        longest_loss = max(longest_loss, current_loss)
    return {"longest_winning_streak": longest_win, "longest_losing_streak": longest_loss}
