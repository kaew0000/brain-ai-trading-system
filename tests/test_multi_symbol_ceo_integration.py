"""
tests/test_multi_symbol_ceo_integration.py — V16 Phase 4B Step 3B: CEO
Decision Context + Multi-Symbol Signal Integration

Part E's three required test areas:
  1. Single Symbol — the legacy CEOAgent.decide() caller produces
     identical action/confidence/score/weights before and after this
     phase (decide_from_context() is a transparent wrapper).
  2. Multi Symbol — BTCUSDT/ETHUSDT/SOLUSDT each produce independent
     CEODecision/AgentReports with correct symbol propagation and no
     cross-symbol contamination.
  3. No Duplicate Computation — MarketContextBuilder.build() and
     ConfidenceEngine.score() are each called exactly once per symbol;
     CEOAgent reuses PortfolioSignalProvider's existing outputs rather
     than recomputing them.

Uses FakeDataProvider/_full_market_data from
tests/test_portfolio_signal_provider.py (imported, not duplicated —
those are this suite's own established multi-symbol OHLCV fixtures)
but a locally-defined FakeAgent, matching
tests/test_symbol_isolation.py's own stated convention of colocating
fixture helpers per file rather than importing them cross-file.
"""
from __future__ import annotations

import pytest

from agents.base_agent import AgentReport, BaseAgent
from agents.ceo_agent import CEOAgent
from agents.decision_context import CEODecisionContext
from agents.multi_symbol_adapter import MultiSymbolCEOAdapter
from decision.confidence_engine import ConfidenceEngine
from execution.portfolio_signal_provider import PortfolioSignalProvider, SignalWithContext
from intelligence.market_context_builder import MarketContextBuilder
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    # Same isolation convention tests/test_symbol_isolation.py and
    # tests/test_ceo_ensemble_fusion.py already use — CEOAgent.decide()
    # publishes to shared, process-wide event-bus/telemetry/reasoning
    # singletons.
    from events.event_bus import reset_event_bus as _reset
    _reset(journal=None, persist=False)
    yield
    _reset(journal=None, persist=False)


class FakeAgent(BaseAgent):
    """Minimal stub — same pattern as tests/test_symbol_isolation.py's
    FakeAgent. Reads market_context["symbol"] so tests exercise the
    real symbol-threading path through CEOAgent.decide(), not just a
    hardcoded report."""

    def __init__(self, name: str, signal: str = "LONG", confidence: float = 60.0):
        self.AGENT_NAME = name
        super().__init__()
        self._signal = signal
        self._confidence = confidence

    def analyse(self, market_context: dict) -> AgentReport:
        return AgentReport(agent=self.AGENT_NAME, signal=self._signal,
                            confidence=self._confidence,
                            symbol=market_context.get("symbol"))


# ══════════════════════════════════════════════════════════════════════════
# Part A — CEODecisionContext
# ══════════════════════════════════════════════════════════════════════════

class TestCEODecisionContext:

    def test_construction_with_required_fields_only(self):
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT"})
        assert ctx.symbol == "BTCUSDT"
        assert ctx.confidence_result is None
        assert ctx.portfolio_state is None
        assert ctx.existing_positions == ()
        assert ctx.risk_snapshot is None

    def test_is_frozen(self):
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={})
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            ctx.symbol = "ETHUSDT"

    def test_existing_positions_defaults_do_not_share_state_across_instances(self):
        """default_factory=tuple, not a single shared mutable default."""
        ctx1 = CEODecisionContext(symbol="A", market_context={})
        ctx2 = CEODecisionContext(symbol="B", market_context={}, existing_positions=("pos1",))
        assert ctx1.existing_positions == ()
        assert ctx2.existing_positions == ("pos1",)

    def test_optional_fields_can_all_be_set(self):
        ctx = CEODecisionContext(
            symbol="BTCUSDT", market_context={"symbol": "BTCUSDT"},
            confidence_result="fake_confidence_result",
            portfolio_state="fake_portfolio_state",
            existing_positions=("pos1", "pos2"),
            risk_snapshot={"can_trade": True},
        )
        assert ctx.confidence_result == "fake_confidence_result"
        assert ctx.portfolio_state == "fake_portfolio_state"
        assert ctx.existing_positions == ("pos1", "pos2")
        assert ctx.risk_snapshot == {"can_trade": True}


# ══════════════════════════════════════════════════════════════════════════
# Part B — PortfolioSignalProvider.get_signal_with_context()
# ══════════════════════════════════════════════════════════════════════════

class TestGetSignalWithContext:

    def test_returns_signal_with_context_or_none(self):
        provider = PortfolioSignalProvider(data_provider=FakeDataProvider())
        result = provider.get_signal_with_context("BTCUSDT")
        assert result is None or isinstance(result, SignalWithContext)

    def test_market_context_and_confidence_result_populated_even_on_wait(self):
        """The whole point of Part B: even a WAIT decision (no
        ExecutionSignal) still carries the market_context/
        confidence_result a CEOAgent-based caller needs — get_signal()
        alone would have discarded both."""
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        result = provider.get_signal_with_context("BTCUSDT")
        assert result is not None
        assert isinstance(result.market_context, dict)
        assert result.market_context.get("symbol") == "BTCUSDT"
        assert result.confidence_result is not None

    def test_get_signal_and_get_signal_with_context_agree_on_signal(self):
        """Same underlying data (FakeDataProvider is deterministic per
        symbol) -> .signal must equal what get_signal() alone returns,
        since get_signal() now delegates to this same computation."""
        dp = FakeDataProvider(data_by_symbol={"ETHUSDT": _full_market_data(trend="down")})
        provider = PortfolioSignalProvider(data_provider=dp)
        via_plain = provider.get_signal("ETHUSDT")
        via_context = provider.get_signal_with_context("ETHUSDT")
        assert via_context is not None
        assert via_plain == via_context.signal

    def test_incomplete_ohlcv_returns_none_same_as_get_signal(self):
        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": {"ohlcv": {"h4": _full_market_data()["ohlcv"]["h4"]}, "mark_price": 100.0},
        })
        provider = PortfolioSignalProvider(data_provider=dp)
        assert provider.get_signal_with_context("BTCUSDT") is None

    def test_never_raises_on_data_provider_failure(self):
        dp = FakeDataProvider(raise_for={"BTCUSDT"})
        provider = PortfolioSignalProvider(data_provider=dp)
        assert provider.get_signal_with_context("BTCUSDT") is None


class TestNoDuplicateComputationWithinPortfolioSignalProvider:
    """Confirms get_signal() and get_signal_with_context() share ONE
    computation path (_compute_signal_with_context) rather than each
    doing their own MarketContextBuilder/ConfidenceEngine call."""

    def test_market_context_builder_called_once_per_get_signal_with_context_call(self):
        calls = []

        class SpyContextBuilder(MarketContextBuilder):
            def build(self, *a, **kw):
                calls.append(kw.get("symbol"))
                return super().build(*a, **kw)

        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp, context_builder=SpyContextBuilder())
        provider.get_signal_with_context("BTCUSDT")
        assert calls == ["BTCUSDT"]

    def test_confidence_engine_called_once_per_get_signal_with_context_call(self):
        calls = []

        class SpyConfidenceEngine(ConfidenceEngine):
            def score(self, *a, **kw):
                calls.append(kw.get("direction"))
                return super().score(*a, **kw)

        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp, confidence_engine=SpyConfidenceEngine())
        provider.get_signal_with_context("BTCUSDT")
        assert len(calls) == 1


# ══════════════════════════════════════════════════════════════════════════
# Part C — CEOAgent.decide_from_context()
# ══════════════════════════════════════════════════════════════════════════

class TestDecideFromContext:

    def test_identical_action_confidence_score_weights_as_legacy_decide(self):
        """Part E "Single Symbol": the legacy call shape and the new
        context-based call shape must agree exactly."""
        market_context = {"symbol": "BTCUSDT", "some": "data"}
        confidence_result = None

        ceo_legacy = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0),
                                        "regime": FakeAgent("REGIME_ANALYST", "LONG", 70.0)})
        ceo_context = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0),
                                         "regime": FakeAgent("REGIME_ANALYST", "LONG", 70.0)})

        dec_legacy = ceo_legacy.decide(market_context, confidence_result)
        dec_context = ceo_context.decide_from_context(
            CEODecisionContext(symbol="BTCUSDT", market_context=market_context,
                                confidence_result=confidence_result)
        )

        assert dec_legacy.action == dec_context.action
        assert dec_legacy.confidence == dec_context.confidence
        assert dec_legacy.score_breakdown == dec_context.score_breakdown
        assert dec_legacy.weights_used == dec_context.weights_used
        assert dec_legacy.agreement_score == dec_context.agreement_score

    def test_extra_context_fields_do_not_affect_the_decision(self):
        """portfolio_state/existing_positions/risk_snapshot are NOT
        consumed by decide_from_context() in this phase — a context
        carrying them must produce the exact same decision as one that
        doesn't."""
        market_context = {"symbol": "BTCUSDT"}
        ceo1 = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0)})
        ceo2 = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 80.0)})

        dec_bare = ceo1.decide_from_context(
            CEODecisionContext(symbol="BTCUSDT", market_context=market_context)
        )
        dec_rich = ceo2.decide_from_context(
            CEODecisionContext(
                symbol="BTCUSDT", market_context=market_context,
                portfolio_state="fake_state", existing_positions=("pos1",),
                risk_snapshot={"can_trade": False},
            )
        )
        assert dec_bare.action == dec_rich.action
        assert dec_bare.confidence == dec_rich.confidence
        assert dec_bare.score_breakdown == dec_rich.score_breakdown

    def test_symbol_propagates_via_market_context_not_context_symbol_field(self):
        """Documented in decision_context.py: the resulting
        CEODecision.symbol comes from market_context["symbol"] via the
        unchanged decide() logic, not directly from context.symbol."""
        ceo = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "ETHUSDT"})
        dec = ceo.decide_from_context(ctx)
        assert dec.symbol == "ETHUSDT"  # from market_context, matching plain decide()'s existing behavior


# ══════════════════════════════════════════════════════════════════════════
# Part D — MultiSymbolCEOAdapter
# ══════════════════════════════════════════════════════════════════════════

def _make_adapter(agents=None):
    dp = FakeDataProvider(data_by_symbol={
        "BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up",   price=60000.0),
        "ETHUSDT": _full_market_data(symbol="ETHUSDT", trend="down", price=3000.0),
        "SOLUSDT": _full_market_data(symbol="SOLUSDT", trend="flat", price=150.0),
    })
    provider = PortfolioSignalProvider(data_provider=dp)
    ceo = CEOAgent(agents=agents or {"smc": FakeAgent("SMC_ANALYST", "LONG", 75.0)})
    return MultiSymbolCEOAdapter(signal_provider=provider, ceo_agent=ceo), dp


class TestMultiSymbolCEOAdapterSingleSymbol:

    def test_decide_returns_a_ceo_decision(self):
        adapter, _ = _make_adapter()
        dec = adapter.decide("BTCUSDT")
        assert dec is not None
        assert dec.symbol == "BTCUSDT"

    def test_call_dunder_matches_decide(self):
        adapter, _ = _make_adapter()
        # Same fake CEOAgent/provider — deterministic data per symbol —
        # both call styles must agree.
        via_decide = adapter.decide("BTCUSDT")
        via_call = adapter("BTCUSDT")
        assert via_decide.action == via_call.action
        assert via_decide.confidence == via_call.confidence

    def test_returns_none_for_unusable_symbol_without_raising(self):
        dp = FakeDataProvider(data_by_symbol={"BADUSDT": {"ohlcv": {}, "mark_price": 0.0}})
        provider = PortfolioSignalProvider(data_provider=dp)
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        assert adapter.decide("BADUSDT") is None

    def test_signal_provider_exception_does_not_raise(self):
        dp = FakeDataProvider(raise_for={"BTCUSDT"})
        provider = PortfolioSignalProvider(data_provider=dp)
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        assert adapter.decide("BTCUSDT") is None


class TestMultiSymbolCEOAdapterMultiSymbol:
    """Part E 'Multi Symbol': BTCUSDT/ETHUSDT/SOLUSDT each produce
    independent CEODecision/AgentReports with correct symbol
    propagation and no cross-symbol contamination."""

    def test_each_symbol_gets_its_own_decision_with_correct_symbol(self):
        adapter, dp = _make_adapter()
        decisions = {s: adapter.decide(s) for s in ("BTCUSDT", "ETHUSDT", "SOLUSDT")}
        for symbol, dec in decisions.items():
            assert dec is not None
            assert dec.symbol == symbol

    def test_agent_reports_carry_the_correct_symbol_per_decision(self):
        adapter, _ = _make_adapter(agents={"smc": FakeAgent("SMC_ANALYST", "LONG", 75.0)})
        for symbol in ("BTCUSDT", "ETHUSDT", "SOLUSDT"):
            dec = adapter.decide(symbol)
            assert dec.agent_reports["smc"]["symbol"] == symbol

    def test_data_provider_requested_each_symbol_independently(self):
        adapter, dp = _make_adapter()
        adapter.decide("BTCUSDT")
        adapter.decide("ETHUSDT")
        adapter.decide("SOLUSDT")
        assert dp.requested_symbols == ["BTCUSDT", "ETHUSDT", "SOLUSDT"]

    def test_no_cross_symbol_contamination_in_market_context(self):
        """Each decide() call builds a brand-new CEODecisionContext from
        that call's own get_signal_with_context() result — confirm
        ETHUSDT's decision doesn't carry BTCUSDT's market_context."""
        adapter, _ = _make_adapter()
        dec_btc = adapter.decide("BTCUSDT")
        dec_eth = adapter.decide("ETHUSDT")
        assert dec_btc.symbol != dec_eth.symbol
        # Independently-fetched market data per symbol (different mark
        # prices in _make_adapter's fixture) -> different confidence
        # inputs; at minimum the two decisions' raw agent report symbols
        # must not cross over.
        assert dec_btc.agent_reports["smc"]["symbol"] == "BTCUSDT"
        assert dec_eth.agent_reports["smc"]["symbol"] == "ETHUSDT"

    def test_sequential_calls_do_not_share_context_object_identity(self):
        adapter, _ = _make_adapter()
        dec_btc = adapter.decide("BTCUSDT")
        dec_eth = adapter.decide("ETHUSDT")
        assert dec_btc.agent_reports is not dec_eth.agent_reports


# ══════════════════════════════════════════════════════════════════════════
# Part E — No Duplicate Computation (full adapter pipeline)
# ══════════════════════════════════════════════════════════════════════════

class TestNoDuplicateComputationThroughAdapter:

    def test_market_context_builder_called_exactly_once_per_symbol(self):
        calls = []

        class SpyContextBuilder(MarketContextBuilder):
            def build(self, *a, **kw):
                calls.append(kw.get("symbol"))
                return super().build(*a, **kw)

        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up"),
            "ETHUSDT": _full_market_data(symbol="ETHUSDT", trend="down"),
        })
        provider = PortfolioSignalProvider(data_provider=dp, context_builder=SpyContextBuilder())
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        adapter.decide("BTCUSDT")
        adapter.decide("ETHUSDT")
        assert calls == ["BTCUSDT", "ETHUSDT"]  # exactly one call per symbol, no repeats

    def test_confidence_engine_called_exactly_once_per_symbol(self):
        calls = []

        class SpyConfidenceEngine(ConfidenceEngine):
            def score(self, *a, **kw):
                calls.append(kw.get("market_context", {}).get("symbol"))
                return super().score(*a, **kw)

        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up"),
            "ETHUSDT": _full_market_data(symbol="ETHUSDT", trend="down"),
        })
        provider = PortfolioSignalProvider(data_provider=dp, confidence_engine=SpyConfidenceEngine())
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        adapter.decide("BTCUSDT")
        adapter.decide("ETHUSDT")
        assert calls == ["BTCUSDT", "ETHUSDT"]

    def test_ceo_agent_sub_agents_receive_the_full_built_context(self):
        """The sub-agent (FakeAgent here, a real analyst in production)
        must see the actual rich market_context dict
        get_signal_with_context() built (has "mtf_direction" etc.) —
        not some stripped-down dict reconstructed by the adapter
        itself, which would be a form of duplicate/parallel
        computation even if it didn't call MarketContextBuilder again."""
        seen_contexts = []

        class RecordingAgent(BaseAgent):
            AGENT_NAME = "SMC_ANALYST"

            def analyse(self, market_context):
                seen_contexts.append(market_context)
                return AgentReport(agent=self.AGENT_NAME, signal="LONG", confidence=50.0,
                                    symbol=market_context.get("symbol"))

        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": RecordingAgent()}))
        adapter.decide("BTCUSDT")

        assert len(seen_contexts) == 1
        assert seen_contexts[0]["symbol"] == "BTCUSDT"
        assert "mtf_direction" in seen_contexts[0]  # a real MarketContextBuilder.build() field


class TestDecideWithSignal:
    """V16 Phase 4B Step 3C: decide_with_signal() — the additive method
    a caller needing BOTH the CEODecision AND the underlying priced
    ExecutionSignal (execution/ceo_gated_signal_provider.py) uses
    instead of calling decide() and then re-fetching the signal
    separately, which would duplicate MarketContextBuilder/
    ConfidenceEngine/RegimeEngine computation."""

    def test_matches_decide_for_the_same_input(self):
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        agent = CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")})
        adapter_a = MultiSymbolCEOAdapter(signal_provider=provider, ceo_agent=agent)
        adapter_b = MultiSymbolCEOAdapter(signal_provider=provider, ceo_agent=agent)

        decision_only = adapter_a.decide("BTCUSDT")
        decision_and_signal, signal = adapter_b.decide_with_signal("BTCUSDT")

        assert decision_and_signal.action == decision_only.action
        assert decision_and_signal.confidence == decision_only.confidence

    def test_returns_the_underlying_execution_signal(self):
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        decision, signal = adapter.decide_with_signal("BTCUSDT")
        # signal may legitimately be None (no MTF consensus this cycle)
        # or an ExecutionSignal — either way it must be the SAME object
        # get_signal_with_context() already produced, not re-derived.
        result = provider.get_signal_with_context("BTCUSDT")
        assert signal == result.signal or (signal is None and result.signal is None)

    def test_returns_none_none_for_unusable_symbol(self):
        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": {"ohlcv": {"h4": _full_market_data()["ohlcv"]["h4"]}, "mark_price": 100.0},
        })
        provider = PortfolioSignalProvider(data_provider=dp)
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        decision, signal = adapter.decide_with_signal("BTCUSDT")
        assert decision is None
        assert signal is None

    def test_does_not_duplicate_market_context_builder_computation(self):
        calls = []

        class SpyContextBuilder(MarketContextBuilder):
            def build(self, *a, **kw):
                calls.append(kw.get("symbol"))
                return super().build(*a, **kw)

        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp, context_builder=SpyContextBuilder())
        adapter = MultiSymbolCEOAdapter(signal_provider=provider,
                                         ceo_agent=CEOAgent(agents={"smc": FakeAgent("SMC_ANALYST")}))
        adapter.decide_with_signal("BTCUSDT")
        assert calls == ["BTCUSDT"]  # exactly once, not twice
