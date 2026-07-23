"""tests/test_strategy_registry.py — V16 Phase 3A: Strategy Plugin System

Registry-mechanics tests use a fresh StrategyRegistry() instance (not
the module-level singleton) so they can't bleed state into each other
or into the built-in-strategy tests below — matching this project's
existing preference for isolated fakes over shared mutable state.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from execution.execution_orchestrator import ExecutionSignal
from execution.strategy_registry import (
    StrategyRegistry,
    SMCOIRegimeStrategyAdapter,
    build_strategy,
    get_strategy,
    list_strategies,
)

pytestmark = pytest.mark.unit


class FakeDataProvider:
    """Minimal double — PortfolioSignalProvider's constructor only
    stores this, it doesn't call anything on it until get_signal()."""


# ══════════════════════════════════════════════════════════════════════════
# StrategyRegistry mechanics (fresh instance per test)
# ══════════════════════════════════════════════════════════════════════════

class TestStrategyRegistryMechanics:

    def test_register_and_get(self):
        reg = StrategyRegistry()

        def factory(**kw):
            return "built"

        reg.register("demo", factory, description="a demo strategy")
        spec = reg.get("demo")
        assert spec.name == "demo"
        assert spec.factory is factory
        assert spec.description == "a demo strategy"

    def test_build_calls_factory_with_kwargs(self):
        reg = StrategyRegistry()
        reg.register("demo", lambda **kw: kw)
        result = reg.build("demo", foo=1, bar=2)
        assert result == {"foo": 1, "bar": 2}

    def test_duplicate_registration_raises_by_default(self):
        reg = StrategyRegistry()
        reg.register("demo", lambda **kw: None)
        with pytest.raises(ValueError, match="already registered"):
            reg.register("demo", lambda **kw: None)

    def test_duplicate_registration_allowed_with_override(self):
        reg = StrategyRegistry()
        reg.register("demo", lambda **kw: "first")
        reg.register("demo", lambda **kw: "second", override=True)
        assert reg.build("demo") == "second"

    def test_unknown_strategy_raises_key_error_listing_available(self):
        reg = StrategyRegistry()
        reg.register("known_one", lambda **kw: None)
        with pytest.raises(KeyError, match="known_one"):
            reg.get("does_not_exist")

    def test_empty_name_raises(self):
        reg = StrategyRegistry()
        with pytest.raises(ValueError):
            reg.register("", lambda **kw: None)

    def test_list_strategies_sorted_by_name(self):
        reg = StrategyRegistry()
        reg.register("zeta", lambda **kw: None, description="z")
        reg.register("alpha", lambda **kw: None, description="a")
        names = [s["name"] for s in reg.list_strategies()]
        assert names == ["alpha", "zeta"]

    def test_is_registered(self):
        reg = StrategyRegistry()
        assert reg.is_registered("demo") is False
        reg.register("demo", lambda **kw: None)
        assert reg.is_registered("demo") is True


# ══════════════════════════════════════════════════════════════════════════
# Built-in strategies (module-level singleton — these are pre-registered
# at import time by execution/strategy_registry.py itself)
# ══════════════════════════════════════════════════════════════════════════

class TestBuiltInStrategiesRegistered:

    def test_portfolio_signal_provider_is_registered(self):
        names = [s["name"] for s in list_strategies()]
        assert "portfolio_signal_provider" in names

    def test_smc_oi_regime_is_registered(self):
        names = [s["name"] for s in list_strategies()]
        assert "smc_oi_regime" in names

    def test_unknown_name_raises(self):
        with pytest.raises(KeyError, match="Unknown strategy"):
            get_strategy("does_not_exist")


class TestPortfolioSignalProviderFactory:

    def test_builds_real_portfolio_signal_provider(self):
        from execution.portfolio_signal_provider import PortfolioSignalProvider

        provider = build_strategy(
            "portfolio_signal_provider", data_provider=FakeDataProvider()
        )
        assert isinstance(provider, PortfolioSignalProvider)

    def test_missing_data_provider_raises_clear_error(self):
        with pytest.raises(ValueError, match="data_provider"):
            build_strategy("portfolio_signal_provider")


class TestSMCOIRegimeAdapterFactory:

    def test_builds_adapter_when_all_deps_present(self):
        provider = build_strategy(
            "smc_oi_regime",
            decision_engine=object(),
            regime_engine=object(),
            smc_engine=object(),
            volume_engine=object(),
            data_provider=object(),
        )
        assert isinstance(provider, SMCOIRegimeStrategyAdapter)

    def test_missing_deps_raises_clear_error_listing_missing(self):
        with pytest.raises(ValueError, match="decision_engine"):
            build_strategy(
                "smc_oi_regime",
                regime_engine=object(),
                smc_engine=object(),
                volume_engine=object(),
                data_provider=object(),
            )


# ══════════════════════════════════════════════════════════════════════════
# SMCOIRegimeStrategyAdapter conversion logic — tested against a fake
# underlying strategy (bypassing __init__, same pattern as this
# project's other adapter tests) so this is a pure unit test of the
# tuple -> ExecutionSignal conversion, no BrainDecisionEngine needed.
# ══════════════════════════════════════════════════════════════════════════

class _FakeUnderlyingStrategy:
    def __init__(self, direction, entry_price, stop_loss, take_profit):
        self._direction = direction
        self._entry_price = entry_price
        self._stop_loss = stop_loss
        self._take_profit = take_profit

    def generate_signal(self):
        return self._direction, self._stop_loss, self._take_profit

    @property
    def last_decision(self):
        if self._direction == 0:
            return None
        return SimpleNamespace(entry_price=self._entry_price)


def _adapter_with_fake(direction, entry_price=0.0, stop_loss=0.0, take_profit=0.0):
    adapter = SMCOIRegimeStrategyAdapter.__new__(SMCOIRegimeStrategyAdapter)
    adapter._strategy = _FakeUnderlyingStrategy(direction, entry_price, stop_loss, take_profit)
    return adapter


class TestSMCOIRegimeStrategyAdapterConversion:

    def test_long_signal_converts_to_execution_signal(self):
        adapter = _adapter_with_fake(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        result = adapter.get_signal("BTCUSDT")
        assert result == ExecutionSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)

    def test_short_signal_converts_to_execution_signal(self):
        adapter = _adapter_with_fake(direction=-1, entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        result = adapter.get_signal("ETHUSDT")
        assert result == ExecutionSignal(direction=-1, entry_price=100.0, stop_loss=105.0, take_profit=90.0)

    def test_no_trade_direction_returns_none(self):
        adapter = _adapter_with_fake(direction=0)
        assert adapter.get_signal("BTCUSDT") is None

    def test_missing_entry_price_returns_none_not_a_bad_signal(self):
        """Mirrors PortfolioSignalProvider's own "no entry price -> no
        trade" handling rather than emitting a signal with entry=0."""
        adapter = _adapter_with_fake(direction=1, entry_price=0.0, stop_loss=95.0, take_profit=110.0)
        assert adapter.get_signal("BTCUSDT") is None

    def test_call_dunder_matches_get_signal(self):
        adapter = _adapter_with_fake(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        assert adapter("BTCUSDT") == adapter.get_signal("BTCUSDT")

    def test_symbol_argument_is_ignored_by_underlying_strategy(self):
        """Documents the honest limitation from this module's docstring:
        the adapter is not symbol-aware, because SMC_OI_Regime_Strategy
        isn't. Same fake strategy, two different symbols in -> identical
        signal out."""
        adapter = _adapter_with_fake(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        assert adapter.get_signal("BTCUSDT") == adapter.get_signal("ETHUSDT")
