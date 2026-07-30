"""
learning/symbol_statistics.py — V16 Phase 4C Step 1: per-symbol
performance breakdown, one of pattern_miner.py's inputs ("best
symbols", "worst symbols").
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from ._stats_utils import rows_of, trade_stats


@dataclass(frozen=True)
class SymbolStatistics:
    symbol: str
    stats:  dict  # see learning/_stats_utils.py's trade_stats()


def compute_symbol_statistics(dataset_or_rows) -> list[SymbolStatistics]:
    """Sorted by total_pnl descending (best symbol first) — rows with
    no symbol recorded are skipped, not folded into a fake "None"
    bucket."""
    rows = rows_of(dataset_or_rows)
    by_symbol: dict[str, list] = defaultdict(list)
    for r in rows:
        if r.symbol:
            by_symbol[r.symbol].append(r)

    out = [SymbolStatistics(symbol=s, stats=trade_stats(rs)) for s, rs in by_symbol.items()]
    return sorted(out, key=lambda x: x.stats["total_pnl"] if x.stats["total_pnl"] is not None else float("-inf"),
                  reverse=True)
