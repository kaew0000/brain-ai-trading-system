"""
tests/test_symbol_isolation.py — V16 Phase 4B Step 3A

Covers the three additive changes in this bundle:
  1. AgentReport.symbol — every report can now say which symbol it was
     produced for; default None, never fabricated.
  2. CEODecision.symbol — same idea, one level up; preparation only,
     no voting/scoring change.
  3. RegimeEngine.models — one fitted HMM per symbol instead of one
     shared model reused across every symbol (the audit finding this
     bundle exists to fix).

No CEOAgent-multi-symbol integration, no PortfolioSignalProvider change,
no execution/journal change — this file only proves the three additive
building blocks work in isolation, per this bundle's own explicit scope.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from agents.base_agent import AgentReport, BaseAgent
from agents.ceo_agent import CEOAgent, CEODecision
from regime.regime_engine import RegimeEngine

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    # Same isolation convention tests/test_ceo_ensemble_fusion.py already
    # uses — CEOAgent.decide() publishes telemetry/reasoning/event-bus
    # entries that are shared, process-wide singletons (see this phase's
    # own design-audit findings), so tests must reset them to avoid
    # leaking state across test cases.
    from events.event_bus import reset_event_bus as _reset
    _reset(journal=None, persist=False)
    yield
    _reset(journal=None, persist=False)


def _make_ohlcv(n, seed, trend_per_bar=0, noise=100):
    """Same helper as tests/test_regime.py, duplicated locally rather
    than imported cross-file, matching this test suite's existing
    convention of colocated fixture helpers per file."""
    np.random.seed(seed)
    close = 50_000 + np.arange(n) * trend_per_bar + np.random.randn(n) * noise
    close = np.maximum(close, 1_000)
    high  = close + np.abs(np.random.randn(n) * 60)
    low   = close - np.abs(np.random.randn(n) * 60)
    low   = np.maximum(low, 1)
    idx   = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close - 10, "high": high, "low": low,
         "close": close, "volume": np.random.uniform(200, 1_000, n)},
        index=idx,
    )


# ═══════════════════════════════════════════════════════════════════════
# Part A — AgentReport.symbol
# ═══════════════════════════════════════════════════════════════════════

class TestAgentReportSymbol:

    def test_symbol_defaults_to_none(self):
        r = AgentReport(agent="X")
        assert r.symbol is None

    def test_symbol_can_be_set(self):
        r = AgentReport(agent="X", symbol="BTCUSDT")
        assert r.symbol == "BTCUSDT"

    def test_symbol_in_to_dict(self):
        r = AgentReport(agent="X", symbol="BTCUSDT")
        assert r.to_dict()["symbol"] == "BTCUSDT"

    def test_to_dict_symbol_key_present_even_when_none(self):
        # The key must exist (not be silently omitted) so a consumer of
        # to_dict() can distinguish "no symbol" from "field doesn't exist".
        r = AgentReport(agent="X")
        d = r.to_dict()
        assert "symbol" in d
        assert d["symbol"] is None

    def test_existing_positional_and_keyword_construction_unaffected(self):
        # Every pre-existing call site in agents/*.py constructs with
        # `agent=...` as the first kwarg and never passes `symbol` at
        # all — confirm that pattern still works exactly as before.
        r = AgentReport(agent="SMC_ANALYST", signal="LONG", confidence=72.5,
                         summary="test", factors=["a"], raw={"k": "v"})
        assert r.agent == "SMC_ANALYST"
        assert r.symbol is None

    def test_two_reports_different_symbols_retain_independent_symbols(self):
        btc = AgentReport(agent="SMC_ANALYST", signal="LONG", confidence=70.0,
                           symbol="BTCUSDT")
        eth = AgentReport(agent="SMC_ANALYST", signal="SHORT", confidence=55.0,
                           symbol="ETHUSDT")
        assert btc.symbol == "BTCUSDT"
        assert eth.symbol == "ETHUSDT"
        assert btc.symbol != eth.symbol
        # Confirm they're genuinely independent objects, not aliases
        assert btc is not eth

    def test_real_analyst_populates_symbol_from_market_context(self):
        # End-to-end proof using a REAL production analyst (not a test
        # stub) — confirms agents/regime_analyst.py's actual analyse()
        # threads market_context["symbol"] through, not just that the
        # dataclass field itself works in isolation.
        from agents.regime_analyst import RegimeAnalyst
        analyst = RegimeAnalyst()
        ctx = {"symbol": "BTCUSDT", "regime": "TREND", "regime_conf": 0.8,
               "trend_bias": "BULLISH", "trend_strength": 0.7,
               "adx": 30.0, "rsi": 60.0, "mtf_aligned": True}
        report = analyst.run(ctx)
        assert report.symbol == "BTCUSDT"

    def test_real_analyst_does_not_fabricate_symbol_when_absent(self):
        from agents.regime_analyst import RegimeAnalyst
        analyst = RegimeAnalyst()
        ctx = {"regime": "TREND", "regime_conf": 0.8, "trend_bias": "BULLISH",
               "trend_strength": 0.7, "adx": 30.0, "rsi": 60.0, "mtf_aligned": True}
        report = analyst.run(ctx)
        assert report.symbol is None

    def test_real_analyst_sequential_multi_symbol_calls_stay_independent(self):
        # Same analyst instance, called for two different symbols in a
        # row (the actual multi-symbol usage pattern a future CEOAgent
        # integration would exercise) — each returned report must carry
        # its own call's symbol.
        from agents.regime_analyst import RegimeAnalyst
        analyst = RegimeAnalyst()
        base_ctx = {"regime": "TREND", "regime_conf": 0.8, "trend_bias": "BULLISH",
                    "trend_strength": 0.7, "adx": 30.0, "rsi": 60.0, "mtf_aligned": True}
        r1 = analyst.run({**base_ctx, "symbol": "BTCUSDT"})
        r2 = analyst.run({**base_ctx, "symbol": "ETHUSDT"})
        assert r1.symbol == "BTCUSDT"
        assert r2.symbol == "ETHUSDT"


# ═══════════════════════════════════════════════════════════════════════
# Part B — CEODecision.symbol
# ═══════════════════════════════════════════════════════════════════════

class FakeAgent(BaseAgent):
    """Minimal stub — same pattern as tests/test_ceo_ensemble_fusion.py's
    FakeAgent, but its analyse() actually reads market_context["symbol"]
    (the real analysts' new behavior, Part A) instead of ignoring it, so
    these tests exercise the real symbol-threading path through
    CEOAgent.decide(), not just CEODecision's field in isolation."""

    def __init__(self, name: str, signal: str = "LONG", confidence: float = 60.0):
        self.AGENT_NAME = name
        super().__init__()
        self._signal = signal
        self._confidence = confidence

    def analyse(self, market_context: dict) -> AgentReport:
        return AgentReport(agent=self.AGENT_NAME, signal=self._signal,
                            confidence=self._confidence,
                            symbol=market_context.get("symbol"))

    def answer(self, question: str, market_context=None) -> str:
        return "stub"


class TestCEODecisionSymbol:

    def test_symbol_defaults_to_none_on_direct_construction(self):
        dec = CEODecision()
        assert dec.symbol is None

    def test_symbol_in_to_dict(self):
        dec = CEODecision(symbol="BTCUSDT")
        assert dec.to_dict()["symbol"] == "BTCUSDT"

    def test_decide_populates_symbol_from_market_context(self):
        ceo = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        dec = ceo.decide({"symbol": "BTCUSDT"})
        assert dec.symbol == "BTCUSDT"

    def test_decide_symbol_none_when_market_context_lacks_it(self):
        ceo = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        dec = ceo.decide({})
        assert dec.symbol is None

    def test_decide_two_calls_different_symbols_independent_decisions(self):
        ceo = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        dec_btc = ceo.decide({"symbol": "BTCUSDT"})
        dec_eth = ceo.decide({"symbol": "ETHUSDT"})
        assert dec_btc.symbol == "BTCUSDT"
        assert dec_eth.symbol == "ETHUSDT"

    def test_symbol_field_does_not_affect_action_or_confidence(self):
        # "No behavior change / no voting change / no score change" —
        # the same agent votes must produce the same action/confidence
        # regardless of what symbol (or no symbol) is in market_context.
        ceo1 = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0)})
        ceo2 = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0)})
        dec_with_symbol = ceo1.decide({"symbol": "BTCUSDT"})
        dec_without = ceo2.decide({})
        assert dec_with_symbol.action == dec_without.action
        assert dec_with_symbol.confidence == dec_without.confidence
        assert dec_with_symbol.score_breakdown == dec_without.score_breakdown

    def test_analyse_wrapper_also_populates_symbol(self):
        # CEOAgent.analyse() (the BaseAgent-interface wrapper around
        # decide()) has its own separate AgentReport construction site —
        # confirm it independently populates symbol too.
        ceo = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        report = ceo.analyse({"symbol": "BTCUSDT"})
        assert report.symbol == "BTCUSDT"


# ═══════════════════════════════════════════════════════════════════════
# Part C — RegimeEngine per-symbol HMM models
# ═══════════════════════════════════════════════════════════════════════

class TestRegimeEnginePerSymbolModels:

    def test_no_models_fitted_before_any_call(self):
        engine = RegimeEngine(use_hmm=True)
        assert engine.models == {}

    def test_btc_then_eth_then_btc_creates_exactly_two_models(self):
        engine = RegimeEngine(use_hmm=True)
        btc_df  = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        eth_df  = _make_ohlcv(200, seed=20, trend_per_bar=-5, noise=400)
        btc_df2 = _make_ohlcv(200, seed=30, trend_per_bar=15, noise=60)

        engine.classify(btc_df, symbol="BTCUSDT")
        engine.classify(eth_df, symbol="ETHUSDT")
        engine.classify(btc_df2, symbol="BTCUSDT")

        assert set(engine.models.keys()) == {"BTCUSDT", "ETHUSDT"}

    def test_btc_model_object_identity_unchanged_across_calls(self):
        engine = RegimeEngine(use_hmm=True)
        btc_df1 = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        btc_df2 = _make_ohlcv(200, seed=30, trend_per_bar=15, noise=60)

        engine.classify(btc_df1, symbol="BTCUSDT")
        model_after_first_call = engine.models["BTCUSDT"]

        engine.classify(btc_df2, symbol="BTCUSDT")
        model_after_second_call = engine.models["BTCUSDT"]

        assert model_after_first_call is model_after_second_call

    def test_eth_model_object_identity_unchanged_across_calls(self):
        engine = RegimeEngine(use_hmm=True)
        eth_df1 = _make_ohlcv(200, seed=20, trend_per_bar=-5, noise=400)
        eth_df2 = _make_ohlcv(200, seed=40, trend_per_bar=-8, noise=380)

        engine.classify(eth_df1, symbol="ETHUSDT")
        model_after_first_call = engine.models["ETHUSDT"]

        engine.classify(eth_df2, symbol="ETHUSDT")
        model_after_second_call = engine.models["ETHUSDT"]

        assert model_after_first_call is model_after_second_call

    def test_btc_model_is_not_eth_model(self):
        engine = RegimeEngine(use_hmm=True)
        btc_df = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        eth_df = _make_ohlcv(200, seed=20, trend_per_bar=-5, noise=400)

        engine.classify(btc_df, symbol="BTCUSDT")
        engine.classify(eth_df, symbol="ETHUSDT")

        assert engine.models["BTCUSDT"] is not engine.models["ETHUSDT"]

    def test_btc_model_never_reused_for_a_third_symbol(self):
        # Explicit "never reuse BTC model for SOL" proof, not just
        # "BTC != ETH" — check a third, later-introduced symbol too.
        engine = RegimeEngine(use_hmm=True)
        btc_df = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        sol_df = _make_ohlcv(200, seed=50, trend_per_bar=3, noise=250)

        engine.classify(btc_df, symbol="BTCUSDT")
        engine.classify(sol_df, symbol="SOLUSDT")

        assert engine.models["BTCUSDT"] is not engine.models["SOLUSDT"]
        assert len(engine.models) == 2

    def test_omitting_symbol_reproduces_prior_single_shared_model_behavior(self):
        # Backward-compatibility guard: every existing caller (main.py's
        # legacy loop, execution/portfolio_signal_provider.py) omits
        # `symbol` — confirm they still get exactly one shared model,
        # reused across calls, identical to this class's behavior before
        # this bundle.
        engine = RegimeEngine(use_hmm=True)
        df1 = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        df2 = _make_ohlcv(200, seed=20, trend_per_bar=-5, noise=400)

        engine.classify(df1)   # no symbol=
        model_after_first = engine.models[engine._DEFAULT_MODEL_KEY]
        engine.classify(df2)   # no symbol=
        model_after_second = engine.models[engine._DEFAULT_MODEL_KEY]

        assert model_after_first is model_after_second
        assert len(engine.models) == 1

    def test_explicit_symbol_and_omitted_symbol_do_not_collide(self):
        engine = RegimeEngine(use_hmm=True)
        named_df   = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        default_df = _make_ohlcv(200, seed=20, trend_per_bar=-5, noise=400)

        engine.classify(named_df, symbol="BTCUSDT")
        engine.classify(default_df)   # no symbol=

        assert "BTCUSDT" in engine.models
        assert engine._DEFAULT_MODEL_KEY in engine.models
        assert engine.models["BTCUSDT"] is not engine.models[engine._DEFAULT_MODEL_KEY]

    def test_classify_still_returns_valid_regime_result_with_symbol(self):
        # Confirm the symbol parameter doesn't change classify()'s
        # ordinary return contract.
        engine = RegimeEngine(use_hmm=True)
        df = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        result = engine.classify(df, symbol="BTCUSDT")
        assert result.regime in ("TREND", "RANGE", "SQUEEZE", "VOLATILE")
        assert 0.0 <= result.confidence <= 1.0

    def test_use_hmm_false_never_populates_models_dict(self):
        # Rule-based-only mode shouldn't fit anything, symbol or not.
        engine = RegimeEngine(use_hmm=False)
        df = _make_ohlcv(200, seed=10, trend_per_bar=20, noise=50)
        engine.classify(df, symbol="BTCUSDT")
        assert engine.models == {}
