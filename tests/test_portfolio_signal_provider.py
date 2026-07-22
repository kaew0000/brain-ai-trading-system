"""tests/test_portfolio_signal_provider.py — V16 Phase 2F: Execution
Scheduler + Multi-Symbol Signals

Uses the same synthetic-OHLCV generator tests/test_phase3.py already
established (`_make_ohlcv`) rather than inventing a second one, and a
plain fake data_provider test double (matching this project's own
established fake-over-Mock preference for readability) rather than
mocking BinanceDataProvider's internals — this module's job is
orchestrating the pipeline, not validating Binance's API shapes (that's
tests/test_data.py's job).
"""
from __future__ import annotations

import pandas as pd
import pytest

from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
from tests.test_phase3 import _make_ohlcv

pytestmark = pytest.mark.unit


def _full_market_data(symbol="BTCUSDT", trend="up", price=60000.0):
    return {
        "ohlcv": {
            "h4":  _make_ohlcv(100, trend=trend, start=price),
            "h1":  _make_ohlcv(150, trend=trend, start=price),
            "m15": _make_ohlcv(250, trend=trend, start=price),
        },
        "mark_price":    price,
        "open_interest": 1000.0,
        "funding_rate":  0.0001,
        "ls_ratio":      {},
        "taker_ratio":   {},
        "oi_delta":      0.01,
        "oi_history":    [],
    }


class FakeDataProvider:
    """Records every symbol it was asked for — lets tests assert the
    provider is actually threading the symbol through, not silently
    reusing settings.SYMBOL somewhere."""

    def __init__(self, data_by_symbol=None, raise_for=None):
        self.data_by_symbol = data_by_symbol or {}
        self.raise_for = raise_for or set()
        self.requested_symbols: list[str] = []

    def get_market_data_for(self, symbol):
        self.requested_symbols.append(symbol)
        if symbol in self.raise_for:
            raise ConnectionError(f"simulated failure for {symbol}")
        return self.data_by_symbol.get(symbol, _full_market_data(symbol))


class TestBasicPipeline:

    def test_returns_none_or_signal_without_raising(self):
        """With synthetic random-walk data, the exact confidence outcome
        isn't asserted here (that's confidence_engine's own test
        coverage) — what's under test is that the full pipeline runs
        end-to-end without error and returns a well-typed result."""
        provider = PortfolioSignalProvider(data_provider=FakeDataProvider())
        result = provider.get_signal("BTCUSDT")
        assert result is None or isinstance(result, ExecutionSignal)

    def test_call_dunder_matches_get_signal(self):
        dp = FakeDataProvider()
        provider = PortfolioSignalProvider(data_provider=dp)
        # Same underlying data each call (FakeDataProvider is
        # deterministic per symbol via _make_ohlcv's fixed seed), so
        # both call styles must agree.
        via_call = provider("ETHUSDT")
        via_method = provider.get_signal("ETHUSDT")
        assert via_call == via_method

    def test_threads_the_requested_symbol_through_to_data_provider(self):
        dp = FakeDataProvider()
        provider = PortfolioSignalProvider(data_provider=dp)
        provider.get_signal("SOLUSDT")
        assert dp.requested_symbols == ["SOLUSDT"]

    def test_different_symbols_are_independent_calls(self):
        dp = FakeDataProvider()
        provider = PortfolioSignalProvider(data_provider=dp)
        provider.get_signal("BTCUSDT")
        provider.get_signal("ETHUSDT")
        assert dp.requested_symbols == ["BTCUSDT", "ETHUSDT"]


class TestSafetyGuards:

    def test_missing_h1_or_m15_returns_none_without_raising(self):
        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": {"ohlcv": {"h4": _make_ohlcv(50)}, "mark_price": 100.0},
        })
        provider = PortfolioSignalProvider(data_provider=dp)
        assert provider.get_signal("BTCUSDT") is None

    def test_empty_ohlcv_dict_returns_none(self):
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": {"ohlcv": {}, "mark_price": 100.0}})
        provider = PortfolioSignalProvider(data_provider=dp)
        assert provider.get_signal("BTCUSDT") is None

    def test_data_provider_exception_is_caught_not_raised(self):
        dp = FakeDataProvider(raise_for={"BTCUSDT"})
        provider = PortfolioSignalProvider(data_provider=dp)
        result = provider.get_signal("BTCUSDT")  # must not raise
        assert result is None

    def test_one_symbol_failing_does_not_affect_another(self):
        """The realistic multi-symbol scenario this whole module exists
        for: ExecutionScheduler will call get_signal() for several
        symbols in a row — one bad one must not poison the rest."""
        dp = FakeDataProvider(raise_for={"BADUSDT"})
        provider = PortfolioSignalProvider(data_provider=dp)
        bad_result = provider.get_signal("BADUSDT")
        good_result = provider.get_signal("BTCUSDT")
        assert bad_result is None
        assert good_result is None or isinstance(good_result, ExecutionSignal)

    def test_zero_mark_price_returns_none(self):
        data = _full_market_data()
        data["mark_price"] = 0.0
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": data})
        provider = PortfolioSignalProvider(data_provider=dp)
        assert provider.get_signal("BTCUSDT") is None


class TestSharedEngineInjection:
    """Confirms constructor-injected engines are actually used (not
    silently replaced by fresh defaults) — this matters because
    production wiring (main.py) passes the SAME engine instances
    build_system() already constructed, specifically to avoid
    pointless duplicate construction."""

    def test_injected_regime_engine_is_used(self):
        calls = []

        class SpyRegimeEngine:
            def classify(self, df):
                calls.append(df)
                from regime.regime_engine import RegimeResult
                return RegimeResult(regime="RANGE", confidence=0.5)

        provider = PortfolioSignalProvider(data_provider=FakeDataProvider(), regime_engine=SpyRegimeEngine())
        provider.get_signal("BTCUSDT")
        assert len(calls) == 1
        assert isinstance(calls[0], pd.DataFrame)

    def test_default_engines_constructed_when_not_provided(self):
        # Must not raise — every engine should have a sensible default.
        provider = PortfolioSignalProvider(data_provider=FakeDataProvider())
        assert provider.regime_engine is not None
        assert provider.smc_engine is not None
        assert provider.volume_engine is not None
        assert provider.context_builder is not None
        assert provider.confidence_engine is not None


class TestSymbolPassedToContextBuilder:

    def test_context_builder_receives_the_correct_symbol(self):
        """Regression guard for the exact bug this phase's own fix
        prevents: MarketContextBuilder.build() used to hardcode
        settings.SYMBOL. If that regressed, every multi-symbol context
        would silently claim to be for settings.SYMBOL regardless of
        which symbol was actually analyzed."""
        captured = {}
        real_builder_cls = None
        from intelligence.market_context_builder import MarketContextBuilder

        class SpyContextBuilder(MarketContextBuilder):
            def build(self, *args, **kwargs):
                captured["symbol"] = kwargs.get("symbol")
                return super().build(*args, **kwargs)

        provider = PortfolioSignalProvider(data_provider=FakeDataProvider(), context_builder=SpyContextBuilder())
        provider.get_signal("ETHUSDT")
        assert captured["symbol"] == "ETHUSDT"
