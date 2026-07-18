"""tests/test_correlation_engine.py — V16 Phase 2A"""
from __future__ import annotations

import pytest

from portfolio.correlation_engine import CorrelationEngine
from portfolio.portfolio_models import CorrelationTier

pytestmark = pytest.mark.unit


class TestTierExamplesFromTheBrief:
    """The three examples given verbatim in the Phase 2A brief."""

    def test_btc_eth_is_high(self):
        assert CorrelationEngine.get_tier("BTCUSDT", "ETHUSDT") == CorrelationTier.HIGH

    def test_btc_sol_is_medium(self):
        assert CorrelationEngine.get_tier("BTCUSDT", "SOLUSDT") == CorrelationTier.MEDIUM

    def test_btc_doge_is_low(self):
        assert CorrelationEngine.get_tier("BTCUSDT", "DOGEUSDT") == CorrelationTier.LOW


class TestTierLookup:

    def test_same_cluster_is_high(self):
        # SOL and BNB are both LARGE_CAP_L1
        assert CorrelationEngine.get_tier("SOLUSDT", "BNBUSDT") == CorrelationTier.HIGH

    def test_same_super_group_different_cluster_is_medium(self):
        # ARB (L2_SCALING) and UNI (DEFI_BLUECHIP) are both ALT_ECOSYSTEM
        assert CorrelationEngine.get_tier("ARBUSDT", "UNIUSDT") == CorrelationTier.MEDIUM

    def test_different_super_group_is_low(self):
        # XMR (PRIVACY) vs SOL (BLUE_CHIP)
        assert CorrelationEngine.get_tier("XMRUSDT", "SOLUSDT") == CorrelationTier.LOW

    def test_unlisted_symbol_is_unknown(self):
        assert CorrelationEngine.get_tier("BTCUSDT", "TOTALLYMADEUPCOINUSDT") == CorrelationTier.UNKNOWN

    def test_both_unlisted_is_unknown(self):
        assert CorrelationEngine.get_tier("FOOCOINUSDT", "BARCOINUSDT") == CorrelationTier.UNKNOWN

    def test_symbol_against_itself_is_high(self):
        assert CorrelationEngine.get_tier("BTCUSDT", "BTCUSDT") == CorrelationTier.HIGH

    def test_lookup_is_symmetric(self):
        assert (CorrelationEngine.get_tier("BTCUSDT", "SOLUSDT")
                == CorrelationEngine.get_tier("SOLUSDT", "BTCUSDT"))

    def test_quote_suffix_stripping_handles_busd_and_usdc(self):
        assert CorrelationEngine.get_tier("BTCBUSD", "ETHUSDC") == CorrelationTier.HIGH


class TestPenaltyMapping:

    def test_penalty_values_match_the_brief_exactly(self):
        assert CorrelationEngine.get_penalty(CorrelationTier.LOW)     == 1.00
        assert CorrelationEngine.get_penalty(CorrelationTier.MEDIUM) == 0.75
        assert CorrelationEngine.get_penalty(CorrelationTier.HIGH)   == 0.50
        assert CorrelationEngine.get_penalty(CorrelationTier.UNKNOWN) == 0.25

    def test_pairwise_returns_tier_and_matching_penalty(self):
        tier, penalty = CorrelationEngine.pairwise("BTCUSDT", "ETHUSDT")
        assert tier == CorrelationTier.HIGH
        assert penalty == 0.50


class TestSeverityOrdering:

    def test_unknown_is_more_severe_than_high(self):
        assert CorrelationEngine.is_at_least_as_severe(CorrelationTier.UNKNOWN, CorrelationTier.HIGH)

    def test_low_is_not_at_least_as_severe_as_medium(self):
        assert not CorrelationEngine.is_at_least_as_severe(CorrelationTier.LOW, CorrelationTier.MEDIUM)

    def test_tier_is_at_least_as_severe_as_itself(self):
        assert CorrelationEngine.is_at_least_as_severe(CorrelationTier.HIGH, CorrelationTier.HIGH)


class TestWorstAgainstPortfolio:

    def test_empty_portfolio_gives_low_no_penalty(self):
        tier, penalty, against = CorrelationEngine.worst_against_portfolio("BTCUSDT", [])
        assert tier == CorrelationTier.LOW
        assert penalty == 1.0
        assert against is None

    def test_picks_the_worst_not_the_average(self):
        # ETH: LOW vs DOGE, HIGH vs BTC (same cluster) -> must report HIGH, not an average
        tier, penalty, against = CorrelationEngine.worst_against_portfolio(
            "ETHUSDT", ["DOGEUSDT", "BTCUSDT"]
        )
        assert tier == CorrelationTier.HIGH
        assert against == "BTCUSDT"
        assert penalty == 0.50

    def test_excludes_the_candidate_itself_from_held_symbols(self):
        """If BTCUSDT is already held and is (degenerately) passed as its
        own candidate, it must not be compared against itself."""
        tier, penalty, against = CorrelationEngine.worst_against_portfolio(
            "BTCUSDT", ["BTCUSDT"]
        )
        assert tier == CorrelationTier.LOW
        assert against is None

    def test_all_low_correlation_holdings_gives_low(self):
        tier, penalty, against = CorrelationEngine.worst_against_portfolio(
            "DOGEUSDT", ["XMRUSDT"]
        )
        assert tier == CorrelationTier.LOW

    def test_unknown_symbol_in_portfolio_is_worst_case(self):
        tier, penalty, against = CorrelationEngine.worst_against_portfolio(
            "BTCUSDT", ["MADEUPCOINUSDT"]
        )
        assert tier == CorrelationTier.UNKNOWN
        assert penalty == 0.25
