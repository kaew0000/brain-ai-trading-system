"""
ranking/score_breakdown.py — V16 Phase 2 Part 2: per-factor scoring

Every function here reads ONLY fields already present on a scanner
SymbolSnapshot (scanner/market_scanner.py) plus cheap universe-wide
statistics computed once per ranking cycle (compute_universe_stats).
Nothing here makes a network call, reads a database, or imports anything
from data/binance_provider.py — that's the actual mechanism behind
"never request Binance data directly, reuse scanner cache only."

Three of the eleven factors the brief asks for — Market Structure, AI
Confidence, Historical Performance — genuinely cannot be computed from
the scanner cache (see module docstring in opportunity_ranker.py for the
full explanation). Their functions here return an explicit UNAVAILABLE
FactorScore rather than inventing a number, so callers (and the API/
dashboard, once built) can distinguish "this symbol looks neutral" from
"we don't actually know."

All scores are 0-100, higher = more favorable to the composite ranking.
Direction (long vs short bias) is intentionally NOT encoded in these
scores — that remains a decision-layer concern, not a ranking concern;
see score_trend's docstring.
"""
from __future__ import annotations

import bisect

from config.settings import settings
from ranking.ranking_models import FactorScore, ScoreBreakdown, ScoreStatus
from scanner.market_scanner import SymbolSnapshot


def _clamp(x: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, x))


# ── Universe-wide statistics (computed once per ranking cycle) ────────────

class UniverseStats:
    """
    Percentile lookups for cross-symbol-relative factors (volume, spread,
    open interest). Built once per rank() call from every valid snapshot,
    then reused for every symbol's score — O(n log n) to build, O(log n)
    per lookup, so scoring the full universe stays fast regardless of
    symbol count (relevant to the <200ms/300-symbols target once this is
    wired into a full pipeline).
    """

    def __init__(self, snapshots: list[SymbolSnapshot]) -> None:
        self._volume_sorted = sorted(s.quote_volume_24h for s in snapshots)
        self._spread_sorted = sorted(s.spread_pct for s in snapshots)
        oi_vals = sorted(s.open_interest for s in snapshots if s.open_interest is not None)
        self._oi_sorted = oi_vals

    @staticmethod
    def _percentile(sorted_vals: list[float], value: float) -> float:
        if not sorted_vals:
            return 50.0
        idx = bisect.bisect_left(sorted_vals, value)
        return 100.0 * idx / max(1, len(sorted_vals) - 1) if len(sorted_vals) > 1 else 50.0

    def volume_percentile(self, value: float) -> float:
        return self._percentile(self._volume_sorted, value)

    def spread_percentile(self, value: float) -> float:
        """Percentile of spread SIZE — higher percentile means WIDER
        spread than peers (worse), caller inverts for a "goodness" score."""
        return self._percentile(self._spread_sorted, value)

    def oi_percentile(self, value: float) -> float:
        return self._percentile(self._oi_sorted, value)

    @property
    def oi_coverage(self) -> int:
        """How many symbols in this cycle actually have OI data (had a detail pass)."""
        return len(self._oi_sorted)


def compute_universe_stats(snapshots: list[SymbolSnapshot]) -> UniverseStats:
    return UniverseStats(snapshots)


# ── Individually-computable factors ────────────────────────────────────────

def score_trend(snap: SymbolSnapshot) -> FactorScore:
    """
    Proxy: trend STRENGTH (not direction) from 24h price change magnitude.
    A large move in either direction = "trending"; near-zero = "ranging".
    This deliberately does not capture direction — a real trend/structure
    read (higher-highs/higher-lows, BOS/CHoCH) needs SMCEngine against an
    OHLCV series, which the scanner cache doesn't carry. See
    opportunity_ranker.py module docstring.
    """
    pct = abs(snap.price_change_pct_24h)
    cap = 10.0  # a 10%+ 24h move is already a strong/extreme trend day
    score = _clamp(pct / cap * 100.0)
    direction = "up" if snap.price_change_pct_24h >= 0 else "down"
    return FactorScore(
        name="trend", score=score, status=ScoreStatus.COMPUTED,
        raw_value=snap.price_change_pct_24h,
        explanation=(
            f"24h move {snap.price_change_pct_24h:+.2f}% ({direction}) — "
            f"magnitude-based trend-strength proxy, not a structural (BOS/CHoCH) read"
        ),
    )


def score_momentum(snap: SymbolSnapshot) -> FactorScore:
    """
    Proxy: 24h price move, adjusted for whether funding rate agrees with
    the move's direction. Funding and price moving the same direction is
    a common signal that a move is being actively chased (real momentum,
    if crowded); funding disagreeing with price direction is treated as a
    mild discount, not a real momentum signal.
    """
    pct = snap.price_change_pct_24h
    base = _clamp(abs(pct) / 10.0 * 100.0)
    funding_agrees = (pct >= 0 and snap.funding_rate >= 0) or (pct < 0 and snap.funding_rate < 0)
    score = base if funding_agrees else base * 0.7
    return FactorScore(
        name="momentum", score=_clamp(score), status=ScoreStatus.COMPUTED,
        raw_value=pct,
        explanation=(
            f"24h move {pct:+.2f}%, funding {'confirms' if funding_agrees else 'diverges from'} "
            f"direction ({snap.funding_rate:+.5f})"
        ),
    )


def score_volume(snap: SymbolSnapshot, stats: UniverseStats) -> FactorScore:
    pct = stats.volume_percentile(snap.quote_volume_24h)
    return FactorScore(
        name="volume", score=pct, status=ScoreStatus.COMPUTED,
        raw_value=snap.quote_volume_24h,
        explanation=f"24h quote volume ${snap.quote_volume_24h:,.0f} — {pct:.0f}th percentile of scanned universe",
    )


def score_liquidity(snap: SymbolSnapshot, stats: UniverseStats) -> FactorScore:
    """
    Composite proxy: volume percentile + spread tightness percentile.
    True liquidity (order-book depth) isn't in the scanner cache — bulk
    book_ticker only carries best bid/ask, not depth — so this blends the
    two cheap signals that correlate with it.
    """
    vol_pct = stats.volume_percentile(snap.quote_volume_24h)
    spread_goodness = 100.0 - stats.spread_percentile(snap.spread_pct)
    score = (vol_pct + spread_goodness) / 2.0
    return FactorScore(
        name="liquidity", score=_clamp(score), status=ScoreStatus.COMPUTED,
        explanation=(
            f"blend of volume percentile ({vol_pct:.0f}) and spread tightness "
            f"percentile ({spread_goodness:.0f}) — proxy, not order-book depth"
        ),
    )


def score_funding(snap: SymbolSnapshot) -> FactorScore:
    """
    Funding near zero = healthy/uncrowded = high score. Extreme funding
    (either sign) = crowded positioning = higher reversal/squeeze risk =
    lower score. Reuses the existing FUNDING_BLOCK_LONG/SHORT thresholds
    (config/settings.py) as the "extreme" reference rather than inventing
    a new constant.
    """
    threshold = max(abs(settings.FUNDING_BLOCK_LONG), abs(settings.FUNDING_BLOCK_SHORT)) or 0.0005
    ratio = abs(snap.funding_rate) / threshold if threshold else 0.0
    score = _clamp(100.0 * (1.0 - min(ratio, 1.0)))
    return FactorScore(
        name="funding", score=score, status=ScoreStatus.COMPUTED,
        raw_value=snap.funding_rate,
        explanation=f"funding rate {snap.funding_rate:+.5f} vs ±{threshold:.5f} extreme threshold",
    )


def score_open_interest(snap: SymbolSnapshot, stats: UniverseStats) -> FactorScore:
    if snap.open_interest is None:
        return FactorScore(
            name="open_interest", score=50.0, status=ScoreStatus.UNAVAILABLE,
            explanation="no OI data yet — symbol hasn't had a detail pass this cycle "
                        "(scanner only fetches OI for the top-N symbols by volume)",
        )
    pct = stats.oi_percentile(snap.open_interest)
    return FactorScore(
        name="open_interest", score=pct, status=ScoreStatus.COMPUTED,
        raw_value=snap.open_interest,
        explanation=(
            f"open interest {snap.open_interest:,.0f} — {pct:.0f}th percentile "
            f"among the {stats.oi_coverage} symbols with OI data this cycle"
        ),
    )


def score_spread(snap: SymbolSnapshot) -> FactorScore:
    cap = 0.0015  # 15 bps treated as a "wide" reference point for perpetuals
    score = _clamp(100.0 * (1.0 - min(snap.spread_pct / cap, 1.0))) if cap else 50.0
    return FactorScore(
        name="spread", score=score, status=ScoreStatus.COMPUTED,
        raw_value=snap.spread_pct,
        explanation=f"bid/ask spread {snap.spread_pct*100:.3f}% (tighter is better, {cap*100:.2f}% treated as wide)",
    )


def score_risk(snap: SymbolSnapshot) -> FactorScore:
    """
    Lower realized volatility (ATR%) → higher score, using the same
    VOLATILITY_RISK_THRESHOLD already used by RiskEngine's dynamic sizing
    (P1-B1) as the reference point, rather than a new constant. This is a
    simplification worth flagging: some strategies WANT volatility for
    bigger moves — here "risk" means "less predictable / harder to size",
    consistent with how RiskEngine already treats volatility.
    """
    if snap.atr_pct is None:
        return FactorScore(
            name="risk", score=50.0, status=ScoreStatus.UNAVAILABLE,
            explanation="no ATR data yet — symbol hasn't had a detail pass this cycle",
        )
    threshold = settings.VOLATILITY_RISK_THRESHOLD or 0.015
    ratio = snap.atr_pct / threshold if threshold else 0.0
    score = _clamp(100.0 * (1.0 - min(ratio, 1.0) * 0.7))  # floor at 30, never fully zero out a volatile symbol
    return FactorScore(
        name="risk", score=score, status=ScoreStatus.COMPUTED,
        raw_value=snap.atr_pct,
        explanation=f"ATR {snap.atr_pct*100:.2f}% of price vs {threshold*100:.2f}% volatility-risk threshold",
    )


# ── Factors that genuinely cannot be computed from scanner cache alone ────

def _unavailable(name: str, reason: str) -> FactorScore:
    return FactorScore(name=name, score=50.0, status=ScoreStatus.UNAVAILABLE, explanation=reason)


def score_market_structure(snap: SymbolSnapshot) -> FactorScore:
    return _unavailable(
        "market_structure",
        "requires SMCEngine against an OHLCV series (BOS/CHoCH/swing analysis) — "
        "not derivable from the scanner's single-point snapshot; needs a per-symbol "
        "kline fetch this module deliberately does not make",
    )


def score_ai_confidence(snap: SymbolSnapshot) -> FactorScore:
    return _unavailable(
        "ai_confidence",
        "requires MarketContextBuilder/ConfidenceEngine, which need their own "
        "multi-timeframe kline fetch per symbol — not run here to avoid "
        "300x-ing the scanner's Binance call volume",
    )


def score_historical_performance(snap: SymbolSnapshot) -> FactorScore:
    return _unavailable(
        "historical_performance",
        "no per-symbol trade history exists yet — this bot has only ever traded "
        "one configured symbol; will populate once multi-symbol executions "
        "accumulate journal history",
    )


# ── Aggregate: one breakdown per symbol ────────────────────────────────────

_ALL_FACTORS = (
    "trend", "market_structure", "momentum", "volume", "funding",
    "open_interest", "liquidity", "spread", "risk", "ai_confidence",
    "historical_performance",
)


def score_symbol(snap: SymbolSnapshot, stats: UniverseStats) -> ScoreBreakdown:
    factors: dict[str, FactorScore] = {
        "trend":                  score_trend(snap),
        "market_structure":       score_market_structure(snap),
        "momentum":               score_momentum(snap),
        "volume":                 score_volume(snap, stats),
        "funding":                score_funding(snap),
        "open_interest":          score_open_interest(snap, stats),
        "liquidity":              score_liquidity(snap, stats),
        "spread":                 score_spread(snap),
        "risk":                   score_risk(snap),
        "ai_confidence":          score_ai_confidence(snap),
        "historical_performance": score_historical_performance(snap),
    }
    assert set(factors) == set(_ALL_FACTORS)  # keep the 11-factor contract honest
    return ScoreBreakdown(symbol=snap.symbol, factors=factors)
