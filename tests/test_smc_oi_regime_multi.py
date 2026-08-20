"""tests/test_smc_oi_regime_multi.py — V16 Phase 4C: Symbol-Aware SMC/OI
Regime Strategy Adapter

Uses plain fake test doubles for every pipeline dependency (matching
this project's established fake-over-Mock preference — see
tests/test_portfolio_signal_provider.py's own docstring) rather than
constructing a real BrainDecisionEngine/RegimeEngine/SMCEngine/
VolumeEngine, since this module's job is orchestration (call order,
symbol threading, VOLATILE skip, entry-price gating), not re-testing
those engines' own internal logic — that's each engine's own test
file's job.
"""
from __future__ import annotations

import pandas as pd
import pytest

from decision.brain_decision_engine import DecisionResult
from execution.execution_orchestrator import ExecutionSignal
from execution.strategy_registry import build_strategy, list_strategies
from execution.smc_oi_regime_multi import SMCOIRegimeMultiAdapter
from regime.regime_engine import RegimeResult
from tests.test_phase3 import _make_ohlcv

pytestmark = pytest.mark.unit


# ── Test doubles ─────────────────────────────────────────────────────────────

def _regime(regime="RANGE", confidence=0.5) -> RegimeResult:
    r = RegimeResult()
    r.regime = regime
    r.confidence = confidence
    return r


def _full_market_data(symbol="BTCUSDT", price=60000.0):
    return {
        "ohlcv": {
            "h4":  _make_ohlcv(100, start=price),
            "h1":  _make_ohlcv(150, start=price),
            "m15": _make_ohlcv(250, start=price),
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
    adapter actually threads the symbol through (V16 Phase 2F's
    get_market_data_for), not silently reusing a global symbol
    somewhere, matching tests/test_portfolio_signal_provider.py's own
    FakeDataProvider pattern."""

    def __init__(self, data_by_symbol=None, raise_for=None):
        self.data_by_symbol = data_by_symbol or {}
        self.raise_for = raise_for or set()
        self.requested_symbols: list[str] = []

    def get_market_data_for(self, symbol):
        self.requested_symbols.append(symbol)
        if symbol in self.raise_for:
            raise ConnectionError(f"simulated failure for {symbol}")
        return self.data_by_symbol.get(symbol, _full_market_data(symbol))


class FakeRegimeEngine:
    """Records (df, symbol) for every classify() call — regression guard
    for the one deviation this module's docstring documents: symbol=
    must reach RegimeEngine so its per-symbol HMM cache activates
    (mirrors tests/test_portfolio_signal_provider.py::
    TestSharedEngineInjection::test_injected_regime_engine_is_used)."""

    def __init__(self, result: RegimeResult | None = None):
        self._result = result or _regime()
        self.calls: list[tuple] = []

    def classify(self, df, symbol=None):
        self.calls.append((df, symbol))
        return self._result


class FakeSMCEngine:
    def analyze_mtf(self, ohlcv):
        return {"h4": None, "h1": None, "m15": None}


class FakeVolumeEngine:
    def analyze(self, df_m15):
        return None


class FakeDecisionEngine:
    """Returns a preset DecisionResult and records every call's kwargs
    so tests can assert the exact market_data/df_m15 handed to it."""

    def __init__(self, result: DecisionResult | None = None):
        self._result = result if result is not None else DecisionResult()
        self.calls: list[dict] = []

    def decide(self, **kwargs):
        self.calls.append(kwargs)
        return self._result


def _build_adapter(
    decision_result=None,
    regime_result=None,
    data_provider=None,
    regime_engine=None,
):
    return SMCOIRegimeMultiAdapter(
        decision_engine=FakeDecisionEngine(decision_result),
        regime_engine=regime_engine or FakeRegimeEngine(regime_result),
        smc_engine=FakeSMCEngine(),
        volume_engine=FakeVolumeEngine(),
        data_provider=data_provider or FakeDataProvider(),
    )


# ══════════════════════════════════════════════════════════════════════════
# Registry wiring
# ══════════════════════════════════════════════════════════════════════════

class TestRegistration:

    def test_smc_oi_regime_multi_is_registered(self):
        names = [s["name"] for s in list_strategies()]
        assert "smc_oi_regime_multi" in names

    def test_smc_oi_regime_still_registered_unchanged(self):
        """The existing legacy entry must survive this phase byte-for-byte."""
        names = [s["name"] for s in list_strategies()]
        assert "smc_oi_regime" in names

    def test_builds_real_adapter_when_all_deps_present(self):
        provider = build_strategy(
            "smc_oi_regime_multi",
            decision_engine=object(),
            regime_engine=object(),
            smc_engine=object(),
            volume_engine=object(),
            data_provider=object(),
        )
        assert isinstance(provider, SMCOIRegimeMultiAdapter)

    def test_missing_deps_raises_clear_error_listing_missing(self):
        with pytest.raises(ValueError, match="decision_engine"):
            build_strategy(
                "smc_oi_regime_multi",
                regime_engine=object(),
                smc_engine=object(),
                volume_engine=object(),
                data_provider=object(),
            )


# ══════════════════════════════════════════════════════════════════════════
# Pipeline orchestration
# ══════════════════════════════════════════════════════════════════════════

class TestHappyPath:

    def test_long_decision_converts_to_execution_signal(self):
        decision = DecisionResult(action="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        adapter = _build_adapter(decision_result=decision)
        result = adapter.get_signal("BTCUSDT")
        assert result == ExecutionSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)

    def test_short_decision_converts_to_execution_signal(self):
        decision = DecisionResult(action="SHORT", entry_price=100.0, stop_loss=105.0, take_profit=90.0)
        adapter = _build_adapter(decision_result=decision)
        result = adapter.get_signal("ETHUSDT")
        assert result == ExecutionSignal(direction=-1, entry_price=100.0, stop_loss=105.0, take_profit=90.0)

    def test_call_dunder_matches_get_signal(self):
        decision = DecisionResult(action="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        adapter = _build_adapter(decision_result=decision)
        assert adapter("BTCUSDT") == adapter.get_signal("BTCUSDT")


class TestNoSignalPath:

    def test_skip_action_returns_none(self):
        adapter = _build_adapter(decision_result=DecisionResult(action="SKIP"))
        assert adapter.get_signal("BTCUSDT") is None

    def test_wait_action_returns_none(self):
        adapter = _build_adapter(decision_result=DecisionResult(action="WAIT"))
        assert adapter.get_signal("BTCUSDT") is None

    def test_volatile_high_confidence_skips_before_decision_engine(self):
        dp = FakeDataProvider()
        decision_engine = FakeDecisionEngine(DecisionResult(action="LONG", entry_price=100.0))
        adapter = SMCOIRegimeMultiAdapter(
            decision_engine=decision_engine,
            regime_engine=FakeRegimeEngine(_regime(regime="VOLATILE", confidence=0.9)),
            smc_engine=FakeSMCEngine(),
            volume_engine=FakeVolumeEngine(),
            data_provider=dp,
        )
        result = adapter.get_signal("BTCUSDT")
        assert result is None
        assert decision_engine.calls == []  # never reached — skipped before decide()

    def test_volatile_low_confidence_does_not_skip(self):
        """Only regime=='VOLATILE' AND confidence>0.75 skips — matches
        SMC_OI_Regime_Strategy.generate_signal()'s exact condition."""
        decision = DecisionResult(action="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        adapter = _build_adapter(
            decision_result=decision,
            regime_result=_regime(regime="VOLATILE", confidence=0.5),
        )
        result = adapter.get_signal("BTCUSDT")
        assert result is not None


class TestMissingEntryPricePath:

    def test_missing_entry_price_returns_none_not_a_bad_signal(self):
        """Mirrors SMCOIRegimeStrategyAdapter's / PortfolioSignalProvider's
        own "no entry price -> no trade" handling."""
        decision = DecisionResult(action="LONG", entry_price=0.0, stop_loss=95.0, take_profit=110.0)
        adapter = _build_adapter(decision_result=decision)
        assert adapter.get_signal("BTCUSDT") is None


class TestSymbolThreading:

    def test_symbol_threaded_to_data_provider(self):
        dp = FakeDataProvider()
        adapter = _build_adapter(data_provider=dp)
        adapter.get_signal("SOLUSDT")
        assert dp.requested_symbols == ["SOLUSDT"]

    def test_symbol_threaded_to_regime_engine(self):
        """Regression guard for this module's documented deviation from
        a literal copy of SMC_OI_Regime_Strategy.generate_signal():
        symbol= must reach RegimeEngine.classify() so its per-symbol HMM
        cache activates instead of pooling every symbol together."""
        regime_engine = FakeRegimeEngine()
        adapter = _build_adapter(regime_engine=regime_engine)
        adapter.get_signal("ETHUSDT")
        assert len(regime_engine.calls) == 1
        assert isinstance(regime_engine.calls[0][0], pd.DataFrame)
        assert regime_engine.calls[0][1] == "ETHUSDT"

    def test_different_symbols_are_independent_calls(self):
        dp = FakeDataProvider()
        adapter = _build_adapter(data_provider=dp)
        adapter.get_signal("BTCUSDT")
        adapter.get_signal("ETHUSDT")
        assert dp.requested_symbols == ["BTCUSDT", "ETHUSDT"]


class TestSafetyGuards:

    def test_missing_h1_or_m15_returns_none_without_raising(self):
        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": {"ohlcv": {"h4": _make_ohlcv(50)}, "mark_price": 100.0},
        })
        adapter = _build_adapter(data_provider=dp)
        assert adapter.get_signal("BTCUSDT") is None

    def test_empty_ohlcv_dict_returns_none(self):
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": {"ohlcv": {}, "mark_price": 100.0}})
        adapter = _build_adapter(data_provider=dp)
        assert adapter.get_signal("BTCUSDT") is None

    def test_data_provider_exception_is_caught_not_raised(self):
        dp = FakeDataProvider(raise_for={"BTCUSDT"})
        adapter = _build_adapter(data_provider=dp)
        result = adapter.get_signal("BTCUSDT")  # must not raise
        assert result is None

    def test_one_symbol_failing_does_not_affect_another(self):
        dp = FakeDataProvider(raise_for={"BADUSDT"})
        decision = DecisionResult(action="LONG", entry_price=100.0, stop_loss=95.0, take_profit=110.0)
        adapter = _build_adapter(decision_result=decision, data_provider=dp)
        bad_result = adapter.get_signal("BADUSDT")
        good_result = adapter.get_signal("BTCUSDT")
        assert bad_result is None
        assert good_result == ExecutionSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)

    def test_decision_engine_exception_is_caught_not_raised(self):
        class RaisingDecisionEngine:
            def decide(self, **kwargs):
                raise RuntimeError("boom")

        adapter = SMCOIRegimeMultiAdapter(
            decision_engine=RaisingDecisionEngine(),
            regime_engine=FakeRegimeEngine(),
            smc_engine=FakeSMCEngine(),
            volume_engine=FakeVolumeEngine(),
            data_provider=FakeDataProvider(),
        )
        assert adapter.get_signal("BTCUSDT") is None


class TestDecisionEngineCallShape:

    def test_decide_called_with_expected_kwargs(self):
        decision_engine = FakeDecisionEngine(DecisionResult(action="SKIP"))
        adapter = SMCOIRegimeMultiAdapter(
            decision_engine=decision_engine,
            regime_engine=FakeRegimeEngine(),
            smc_engine=FakeSMCEngine(),
            volume_engine=FakeVolumeEngine(),
            data_provider=FakeDataProvider(),
        )
        adapter.get_signal("BTCUSDT")
        assert len(decision_engine.calls) == 1
        call = decision_engine.calls[0]
        assert set(call.keys()) == {"smc_signals", "volume_signals", "regime_result", "market_data", "df_m15"}
        assert isinstance(call["df_m15"], pd.DataFrame)
        assert call["market_data"]["mark_price"] == 60000.0
