"""tests/test_ceo_symbol_cache.py — V16 Phase 4B Step 3C: Live CEO Agent
Integration into Multi-Symbol Decision Pipeline

Covers the state-isolation fix agents/multi_symbol_adapter.py's own
docstring flagged as an open risk: sharing one CEOAgent (and therefore
one set of sub-agent instances) across multiple symbols would corrupt
RegimeAnalyst._prev_regime and every agent's _memory/_last.
"""
from __future__ import annotations

import pytest

from agents.ceo_agent import CEOAgent
from agents.ceo_symbol_cache import CEOAgentSymbolCache

pytestmark = pytest.mark.unit


class TestCaching:

    def test_same_symbol_returns_the_same_instance(self):
        cache = CEOAgentSymbolCache()
        a = cache.get_ceo_agent("BTCUSDT")
        b = cache.get_ceo_agent("BTCUSDT")
        assert a is b

    def test_different_symbols_get_different_instances(self):
        cache = CEOAgentSymbolCache()
        btc = cache.get_ceo_agent("BTCUSDT")
        eth = cache.get_ceo_agent("ETHUSDT")
        assert btc is not eth

    def test_every_cached_agent_is_a_real_ceo_agent(self):
        cache = CEOAgentSymbolCache()
        assert isinstance(cache.get_ceo_agent("BTCUSDT"), CEOAgent)

    def test_len_reflects_number_of_distinct_symbols_cached(self):
        cache = CEOAgentSymbolCache()
        cache.get_ceo_agent("BTCUSDT")
        cache.get_ceo_agent("ETHUSDT")
        cache.get_ceo_agent("BTCUSDT")  # repeat — must not grow the cache
        assert len(cache) == 2

    def test_cached_symbols_lists_every_distinct_symbol_once(self):
        cache = CEOAgentSymbolCache()
        cache.get_ceo_agent("BTCUSDT")
        cache.get_ceo_agent("ETHUSDT")
        cache.get_ceo_agent("BTCUSDT")
        assert sorted(cache.cached_symbols) == ["BTCUSDT", "ETHUSDT"]

    def test_btc_eth_btc_uses_exactly_two_agent_layers(self):
        """Mirrors this phase's own required verification for
        RegimeEngine's HMM cache (BTC/ETH/BTC -> two models only) —
        same shape of guarantee for the CEOAgent layer."""
        cache = CEOAgentSymbolCache()
        cache.get_ceo_agent("BTCUSDT")
        cache.get_ceo_agent("ETHUSDT")
        cache.get_ceo_agent("BTCUSDT")
        assert len(cache) == 2


class TestStateIsolation:
    """The actual bug this class exists to fix — verified directly,
    not just inferred from 'different instances'."""

    def test_regime_analyst_prev_regime_is_isolated_per_symbol(self):
        cache = CEOAgentSymbolCache()
        btc_layer = cache.get_agent_layer("BTCUSDT")
        eth_layer = cache.get_agent_layer("ETHUSDT")

        btc_layer["regime"]._prev_regime = "TREND"
        assert eth_layer["regime"]._prev_regime != "TREND"

    def test_base_agent_memory_is_isolated_per_symbol(self):
        cache = CEOAgentSymbolCache()
        btc_layer = cache.get_agent_layer("BTCUSDT")
        eth_layer = cache.get_agent_layer("ETHUSDT")

        from agents.base_agent import AgentReport
        report = AgentReport(agent="SMC_ANALYST", signal="LONG", confidence=80.0, symbol="BTCUSDT")
        btc_layer["smc"]._memory.append(report)

        assert report not in eth_layer["smc"]._memory
        assert len(eth_layer["smc"]._memory) == 0

    def test_every_sub_agent_key_is_a_distinct_instance_across_symbols(self):
        cache = CEOAgentSymbolCache()
        btc_layer = cache.get_agent_layer("BTCUSDT")
        eth_layer = cache.get_agent_layer("ETHUSDT")

        shared_keys = set(btc_layer.keys()) & set(eth_layer.keys())
        assert shared_keys  # sanity: same set of agent names exists in both
        for key in shared_keys:
            assert btc_layer[key] is not eth_layer[key], f"'{key}' is shared across symbols — state will leak"


class TestConstructorArgumentsPassedThrough:

    def test_risk_engine_and_journal_forwarded_to_every_symbols_layer(self):
        risk_engine = object()
        journal = object()
        cache = CEOAgentSymbolCache(risk_engine=risk_engine, journal=journal)

        # RiskManagerAgent / JournalAnalyst hold whatever was passed to
        # build_agent_layer() — spot-check via the CEOAgent's own
        # constructor-injected journal (used for dynamic weighting).
        ceo_btc = cache.get_ceo_agent("BTCUSDT")
        ceo_eth = cache.get_ceo_agent("ETHUSDT")
        assert ceo_btc._journal is journal
        assert ceo_eth._journal is journal
        # Account-wide state is correctly SHARED (not per-symbol) —
        # unlike the sub-agents' _memory/_prev_regime, this is intentional.
        assert ceo_btc._journal is ceo_eth._journal


class TestThreadSafety:

    def test_concurrent_first_access_does_not_create_duplicate_instances(self):
        import threading

        cache = CEOAgentSymbolCache()
        results = []

        def worker():
            results.append(cache.get_ceo_agent("BTCUSDT"))

        threads = [threading.Thread(target=worker) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len({id(r) for r in results}) == 1  # every thread got the SAME instance
        assert len(cache) == 1
