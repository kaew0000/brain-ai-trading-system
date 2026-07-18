"""
portfolio/correlation_engine.py — V16 Phase 2A: Portfolio Intelligence Core

Tier-based correlation lookup — NOT Pearson/statistical correlation. See
config/correlation_table.py's module docstring for the full reasoning
(no historical price series exists anywhere in this codebase yet to
compute real correlation from).

Penalty mapping (multiplicative, applied to a candidate's final_score in
capital_manager.py):
    LOW      → 1.0   no reduction
    MEDIUM   → 0.75
    HIGH     → 0.5
    UNKNOWN  → 0.25  treated as the WORST case, not neutral — an unlisted
                      symbol's true correlation is unverified, and for a
                      live-money portfolio "unverified" should be treated
                      more cautiously than "verified medium/high", not
                      less. This also creates a natural incentive to
                      extend config/correlation_table.py's coverage over
                      time rather than leaving new symbols at a lenient
                      default.
"""
from __future__ import annotations

from typing import Iterable, Optional, Tuple

from config.correlation_table import cluster_of, super_group_of
from portfolio.portfolio_models import CorrelationTier

_PENALTY: dict[CorrelationTier, float] = {
    CorrelationTier.LOW:     1.0,
    CorrelationTier.MEDIUM:  0.75,
    CorrelationTier.HIGH:    0.5,
    CorrelationTier.UNKNOWN: 0.25,
}

# Tier ordering for "worst of" comparisons — HIGH is worse than MEDIUM is
# worse than LOW; UNKNOWN is worst of all (lowest penalty), per the
# reasoning above.
_SEVERITY: dict[CorrelationTier, int] = {
    CorrelationTier.LOW:     0,
    CorrelationTier.MEDIUM:  1,
    CorrelationTier.HIGH:    2,
    CorrelationTier.UNKNOWN: 3,
}


def _base_symbol(symbol: str) -> str:
    """Strips a trailing USDT/BUSD/USDC quote suffix so the table doesn't
    need to be quote-asset-aware. 'BTCUSDT' -> 'BTC'. Symbols already
    without a recognized suffix pass through unchanged."""
    s = symbol.upper()
    for suffix in ("USDT", "BUSD", "USDC", "FDUSD"):
        if s.endswith(suffix) and len(s) > len(suffix):
            return s[: -len(suffix)]
    return s


class CorrelationEngine:
    """Stateless — every method is a pure function of its arguments plus
    the module-level static table. No __init__ state needed, but kept as
    a class (rather than bare functions) for consistency with the other
    portfolio/ engines and so 2B can subclass/swap it (e.g. for a future
    real-correlation implementation) without changing capital_manager.py's
    call sites."""

    @staticmethod
    def get_tier(symbol_a: str, symbol_b: str) -> CorrelationTier:
        if _base_symbol(symbol_a) == _base_symbol(symbol_b):
            # Same symbol compared to itself is the trivial HIGH case —
            # callers normally won't hit this (see worst_against_portfolio,
            # which skips the candidate's own symbol if already held), but
            # defining it avoids an ambiguous UNKNOWN for a degenerate input.
            return CorrelationTier.HIGH

        cluster_a = cluster_of(_base_symbol(symbol_a))
        cluster_b = cluster_of(_base_symbol(symbol_b))
        if cluster_a is None or cluster_b is None:
            return CorrelationTier.UNKNOWN

        if cluster_a == cluster_b:
            return CorrelationTier.HIGH

        group_a = super_group_of(_base_symbol(symbol_a))
        group_b = super_group_of(_base_symbol(symbol_b))
        if group_a is not None and group_a == group_b:
            return CorrelationTier.MEDIUM

        return CorrelationTier.LOW

    @staticmethod
    def get_penalty(tier: CorrelationTier) -> float:
        return _PENALTY[tier]

    @classmethod
    def pairwise(cls, symbol_a: str, symbol_b: str) -> Tuple[CorrelationTier, float]:
        tier = cls.get_tier(symbol_a, symbol_b)
        return tier, cls.get_penalty(tier)

    @classmethod
    def worst_against_portfolio(
        cls, candidate_symbol: str, held_symbols: Iterable[str],
    ) -> Tuple[CorrelationTier, float, Optional[str]]:
        """
        The tier/penalty a candidate should actually be scored on: its
        WORST (most correlated) pairing against anything already held or
        already selected earlier in the same decision cycle — not an
        average. A symbol that's LOW-correlated with four existing
        positions and HIGH-correlated with one should still be treated as
        HIGH: that one redundant exposure is what the correlation check
        exists to catch.

        Returns (tier, penalty, against_symbol). against_symbol is None
        (tier=LOW, penalty=1.0) when held_symbols is empty — nothing to
        be correlated against yet.
        """
        held = [s for s in held_symbols if _base_symbol(s) != _base_symbol(candidate_symbol)]
        if not held:
            return CorrelationTier.LOW, 1.0, None

        worst_tier = CorrelationTier.LOW
        worst_against = None
        for held_symbol in held:
            tier = cls.get_tier(candidate_symbol, held_symbol)
            if _SEVERITY[tier] > _SEVERITY[worst_tier]:
                worst_tier = tier
                worst_against = held_symbol

        return worst_tier, cls.get_penalty(worst_tier), worst_against

    @staticmethod
    def is_at_least_as_severe(tier: CorrelationTier, threshold: CorrelationTier) -> bool:
        """True if `tier` is at least as correlated/severe as `threshold`
        (UNKNOWN counts as more severe than HIGH — see module docstring).
        Public so callers (capital_manager.py's hard-reject check) don't
        need to reach into this module's private severity table."""
        return _SEVERITY[tier] >= _SEVERITY[threshold]
