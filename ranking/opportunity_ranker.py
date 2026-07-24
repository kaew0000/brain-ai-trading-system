"""
ranking/opportunity_ranker.py — V16 Phase 2 Part 2: Opportunity Ranking Engine

    MarketScanner (Part 1)
         |  .get_snapshots()  — READ ONLY, no Binance calls made here
         v
    OpportunityRanker  (this file)
         |  score_breakdown.py   — 11-factor scoring per symbol
         |  confidence_fusion.py — weighted composite + coverage
         v
    Top-N RankedOpportunity list  (consumed next by Portfolio Manager — not built yet)

=== Why 3 of the 11 requested factors are UNAVAILABLE, not computed ===

The brief asks for Trend, Market Structure, Momentum, Volume, Funding,
Open Interest, Liquidity, Spread, Risk, AI Confidence, and Historical
Performance, and separately requires this engine to "never request
Binance data directly, reuse scanner cache only."

scanner/market_scanner.py's SymbolSnapshot carries: price,
price_change_pct_24h, quote_volume_24h, funding_rate, spread_pct,
open_interest, atr_pct. Eight of the eleven factors are real,
honestly-computed proxies from those fields (see score_breakdown.py for
exactly which field backs which factor, and where a name is a proxy for
something deeper — e.g. "trend" here is 24h move magnitude, not a
structural swing-high/low read).

Three are not derivable from that cache at all:
  - Market Structure needs SMCEngine run against an OHLCV series.
  - AI Confidence needs MarketContextBuilder/ConfidenceEngine, which need
    their own multi-timeframe kline fetch.
  - Historical Performance needs per-symbol trade outcomes — this bot has
    only ever traded one configured symbol, so there's no history yet
    for any OTHER symbol regardless of data source.

Computing the first two for real, for every scanned symbol, would mean
running the full per-symbol analysis pipeline ~300 times per ranking
cycle — exactly the Binance-call-volume problem the scanner's two-tier
fetch design (see scanner/market_scanner.py's module docstring) was built
to avoid. So rather than fake a number, score_breakdown.py returns an
explicit UNAVAILABLE FactorScore for these three, and confidence_fusion.py
excludes them from the weighted composite (with the excluded weight
redistributed, not zeroed) rather than diluting every score toward a
placeholder value — see confidence_fusion.py's docstring for the reasoning.

Natural follow-up (not built here, flagging for the next phase): run the
real SMC/Confidence pipeline for only the Ranker's own current top-K
candidates (cheap — that's ~20-40 symbols, not 300) as a second-pass
refinement. That would need its own review since it reintroduces a
(much smaller, bounded) Binance call volume this module currently has
zero of.
"""
from __future__ import annotations

import time

from config.settings import settings
from ranking.confidence_fusion import fuse
from ranking.ranking_models import RankedOpportunity
from ranking.score_breakdown import compute_universe_stats, score_symbol
from ranking import ranking_history
from scanner.market_scanner import MarketScanner
from utils.logger import get_logger

logger = get_logger(__name__)


class OpportunityRanker:
    """
    Usage:
        ranker = OpportunityRanker(scanner)   # scanner: a MarketScanner instance
        top20 = ranker.rank()                 # List[RankedOpportunity], persisted as a side effect
        ranker.get_latest()                   # last computed result, no recompute
    """

    def __init__(self, scanner: MarketScanner, top_n: int | None = None) -> None:
        self._scanner = scanner
        self._top_n   = top_n if top_n is not None else settings.RANKER_TOP_N
        self._last_result: list[RankedOpportunity] = []
        self._last_ranked_at: float | None = None

    def rank(self) -> list[RankedOpportunity]:
        """
        Score every symbol currently in the scanner's cache, fuse to a
        composite, sort descending, keep the top N, persist, and return.
        Pure read of scanner.get_snapshots() — makes no network calls.
        """
        t0 = time.time()
        snapshots = list(self._scanner.get_snapshots().values())

        if not snapshots:
            logger.warning("OpportunityRanker.rank(): scanner cache is empty — nothing to rank yet")
            self._last_result = []
            self._last_ranked_at = time.time()
            return []

        stats = compute_universe_stats(snapshots)
        now = time.time()

        scored: list[RankedOpportunity] = []
        for snap in snapshots:
            breakdown = score_symbol(snap, stats)
            composite, coverage, explanation = fuse(breakdown)
            scored.append(
                RankedOpportunity(
                    rank=0,  # assigned after sort
                    symbol=snap.symbol,
                    composite_score=composite,
                    breakdown=breakdown,
                    explanation=explanation,
                    ranked_at=now,
                    data_age_s=max(0.0, now - snap.scanned_at),
                    coverage=coverage,
                )
            )

        scored.sort(key=lambda o: o.composite_score, reverse=True)
        top = scored[: self._top_n]
        for i, opp in enumerate(top, start=1):
            opp.rank = i

        duration = time.time() - t0
        try:
            ranking_history.save_ranking(top, symbol_count=len(snapshots), duration_s=duration)
        except Exception as exc:
            # save_ranking already has its own internal try/except (mirroring
            # MarketScanner._persist) — this is a second, outer safety net so
            # a bug there can never take down the ranking result itself. The
            # freshly computed `top` list is the valuable, time-sensitive
            # output; persistence is a side effect that must never block it.
            logger.error(f"OpportunityRanker: ranking_history.save_ranking raised unexpectedly: {exc}")

        self._last_result    = top
        self._last_ranked_at = now
        logger.info(
            f"OpportunityRanker.rank() | scored={len(snapshots)} top_n={len(top)} "
            f"duration={duration*1000:.0f}ms"
        )
        return top

    def get_latest(self) -> list[RankedOpportunity]:
        """Last computed result without recomputing — cheap, for API/dashboard reads."""
        return list(self._last_result)

    def status(self) -> dict:
        return {
            "top_n":          self._top_n,
            "last_ranked_at": self._last_ranked_at,
            "result_count":   len(self._last_result),
            "scanner_running": self._scanner.is_running(),
        }
