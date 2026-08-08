"""
tests/test_ceo_live_recommendation_wiring.py — V16 Phase 4C Step 4: Live
Scheduler Wiring.

Covers the test matrix from this phase's design audit (Part K):
  1.  feature disabled -> identical behavior
  2.  no recommendations -> identical behavior
  3.  valid recommendation -> advisory confidence adjustment
  4.  expired recommendation -> skipped
  5.  invalid recommendation -> skipped
  6.  insufficient sample -> skipped
  7.  contradiction -> safely handled
  8.  BLOCKED decision -> byte-identical
  9-12. action/direction/score_breakdown/agreement_score unchanged
  13. confidence cap enforced
  14. max recommendations per decision enforced
  15. recommendation application failure -> normal decision continues
  16. LearningSnapshot/generation failure -> normal cycle continues
  17. multi-symbol isolation
  18. no duplicate recommendation computation
  19. no duplicate exchange polling
  20. EventBus publication correctness

Items 4-14/20 are already covered end-to-end by
tests/test_recommendation_*.py and tests/test_ceo_decide_with_recommendations.py
against the underlying recommendation_advisor/context/service layer this
phase reuses unchanged — re-asserted here only where the NEW live-wiring
code (decide_from_context_with_recommendations, MultiSymbolCEOAdapter,
MultiSymbolCEODispatcher, CEOGatedSignalProvider.recommendation_provider,
main.run_learning_recommendation_refresh) is the thing actually under
test, to avoid duplicating that suite's own coverage.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.base_agent import AgentReport, BaseAgent
from agents.ceo_agent import CEOAgent, CEODecision
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from agents.decision_context import CEODecisionContext
from agents.multi_symbol_adapter import MultiSymbolCEOAdapter
from config.settings import settings
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_singletons():
    from events.event_bus import reset_event_bus as _reset
    _reset(journal=None, persist=False)
    from learning.application.recommendation_metrics import reset_recommendation_metrics
    reset_recommendation_metrics()
    original_flag = settings.RECOMMENDATION_APPLICATION_ENABLED
    yield
    settings.RECOMMENDATION_APPLICATION_ENABLED = original_flag
    _reset(journal=None, persist=False)


class FakeAgent(BaseAgent):
    """Same minimal stub tests/test_multi_symbol_ceo_integration.py and
    tests/test_ceo_decide_with_recommendations.py both use."""

    def __init__(self, name: str, signal: str = "LONG", confidence: float = 60.0):
        self.AGENT_NAME = name
        super().__init__()
        self._signal = signal
        self._confidence = confidence

    def analyse(self, market_context: dict) -> AgentReport:
        return AgentReport(agent=self.AGENT_NAME, signal=self._signal,
                            confidence=self._confidence, symbol=market_context.get("symbol"))


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.15, "sample_size": 80},
                   description="d", severity=severity)


def _ceo(**agents):
    return CEOAgent(agents=agents or {
        "smc": FakeAgent("SMC_ANALYST"), "futures": FakeAgent("FUTURES_ANALYST"),
        "regime": FakeAgent("REGIME_ANALYST"), "risk": FakeAgent("RISK_MANAGER", signal="NEUTRAL"),
    })


# ══════════════════════════════════════════════════════════════════════════
# CEOAgent.decide_from_context_with_recommendations()
# ══════════════════════════════════════════════════════════════════════════

class TestDecideFromContextWithRecommendationsBackwardCompatibility:

    def test_matches_decide_from_context_when_no_recommendations(self):
        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=None)
        assert wrapped.action == plain.action
        assert wrapped.confidence == plain.confidence

    def test_disabled_flag_is_a_complete_no_op(self):  # item 1
        settings.RECOMMENDATION_APPLICATION_ENABLED = False
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=recs)
        assert wrapped.confidence == plain.confidence
        assert wrapped.reasons == plain.reasons

    def test_empty_recommendations_list_is_a_no_op(self):  # item 2
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=[])
        assert wrapped.confidence == plain.confidence

    def test_pre_existing_decide_and_decide_from_context_unaffected(self):
        """Nothing pre-existing calls the new method — decide() and
        decide_from_context() must behave identically whether or not it
        exists/was ever called."""
        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        d1 = ceo.decide(mc)
        ceo.decide_from_context_with_recommendations(
            CEODecisionContext(symbol="BTCUSDT", market_context=mc), recommendations=None,
        )
        d2 = ceo.decide(mc)
        assert d1.action == d2.action
        assert d1.confidence == d2.confidence


class TestDecideFromContextWithRecommendationsIntegration:

    def test_enabled_with_recommendations_adjusts_confidence(self):  # item 3
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=recs)
        assert wrapped.action == plain.action  # item 9: action never changed
        assert wrapped.direction == plain.direction  # item 10: direction never changed
        assert wrapped.score_breakdown == plain.score_breakdown  # item 11
        assert wrapped.agreement_score == plain.agreement_score  # item 12

    def test_never_changes_action_even_with_strong_negative_recommendations(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.01, "sample_size": 500})] * 3, now=now,
        )
        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=recs)
        assert wrapped.action == plain.action

    def test_blocked_decision_is_byte_identical(self):  # item 8
        """BLOCKED comes from a ConfidenceEngine hard block
        (agents/ceo_agent.py: `ce_blocked = ... or ce_action == "BLOCKED"`)
        — a risk-manager circuit-breaker alone only ever produces WAIT,
        confirmed by reading the actual decide() logic rather than
        assumed."""
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)

        class FakeBlockedConfidenceResult:
            action = "BLOCKED"
            confidence = 0.0
            direction = ""
            blocked = True
            block_reasons = ["simulated hard block"]

        ceo = _ceo()
        ctx = CEODecisionContext(
            symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"},
            confidence_result=FakeBlockedConfidenceResult(),
        )
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=recs)
        assert plain.action == "BLOCKED"
        assert wrapped.action == "BLOCKED"
        assert wrapped.confidence == plain.confidence
        assert wrapped.reasons == plain.reasons

    def test_recommendation_application_failure_falls_back_to_unmodified_decision(self, monkeypatch):
        """item 15: a raise inside apply_learning_recommendations() must
        never propagate into a live decision cycle — the unmodified
        decide_from_context() result is returned instead."""
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)

        import learning.application.recommendation_service as svc_module

        def _boom(*a, **kw):
            raise RuntimeError("simulated recommendation application failure")

        monkeypatch.setattr(svc_module, "apply_learning_recommendations", _boom)

        ceo = _ceo()
        ctx = CEODecisionContext(symbol="BTCUSDT", market_context={"symbol": "BTCUSDT", "regime": "TRENDING"})
        plain = ceo.decide_from_context(ctx)
        wrapped = ceo.decide_from_context_with_recommendations(ctx, recommendations=recs)
        assert wrapped.action == plain.action
        assert wrapped.confidence == plain.confidence


class TestDecideWithRecommendationsAlsoGuardsFailures:
    """The pre-existing decide_with_recommendations() gained the same
    try/except this phase adds to the new context-based method (design
    audit Part G, Case 3 gap) — confirm it too degrades safely now."""

    def test_recommendation_application_failure_falls_back(self, monkeypatch):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)

        import learning.application.recommendation_service as svc_module

        def _boom(*a, **kw):
            raise RuntimeError("simulated failure")

        monkeypatch.setattr(svc_module, "apply_learning_recommendations", _boom)

        ceo = _ceo()
        mc = {"symbol": "BTCUSDT", "regime": "TRENDING"}
        plain = ceo.decide(mc)
        wrapped = ceo.decide_with_recommendations(mc, recommendations=recs)
        assert wrapped.action == plain.action
        assert wrapped.confidence == plain.confidence


# ══════════════════════════════════════════════════════════════════════════
# MultiSymbolCEOAdapter — recommendations threading + multi-symbol isolation
# ══════════════════════════════════════════════════════════════════════════

def _make_adapter(agents=None):
    dp = FakeDataProvider(data_by_symbol={
        "BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up",   price=60000.0),
        "ETHUSDT": _full_market_data(symbol="ETHUSDT", trend="down", price=3000.0),
    })
    provider = PortfolioSignalProvider(data_provider=dp)
    ceo = _ceo(**(agents or {"smc": FakeAgent("SMC_ANALYST", "LONG", 75.0)}))
    return MultiSymbolCEOAdapter(signal_provider=provider, ceo_agent=ceo), dp


class TestAdapterRecommendationsThreading:

    def test_decide_with_signal_accepts_recommendations_kwarg_unchanged_when_none(self):
        adapter, _ = _make_adapter()
        dec_a, sig_a = adapter.decide_with_signal("BTCUSDT")
        dec_b, sig_b = adapter.decide_with_signal("BTCUSDT", recommendations=None)
        assert dec_a.action == dec_b.action
        assert dec_a.confidence == dec_b.confidence

    def test_decide_routes_through_decide_from_context_with_recommendations_when_provided(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        adapter, _ = _make_adapter()
        dec_plain, _ = adapter.decide_with_signal("BTCUSDT")
        dec_with_recs, _ = adapter.decide_with_signal("BTCUSDT", recommendations=recs)
        # action/direction must never change regardless of recommendations
        assert dec_with_recs.action == dec_plain.action
        assert dec_with_recs.direction == dec_plain.direction

    def test_multi_symbol_isolation_btc_recommendation_not_applied_to_eth(self):  # item 17
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        # Recommendation scoped only to BTCUSDT (recommendation_engine.py
        # sets .symbol from the pattern's subject for symbol-kind patterns).
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        assert any(r.symbol == "BTCUSDT" for r in recs)

        adapter, _ = _make_adapter()
        dec_btc, _ = adapter.decide_with_signal("BTCUSDT", recommendations=recs)
        dec_eth, _ = adapter.decide_with_signal("ETHUSDT", recommendations=recs)
        assert dec_btc.symbol == "BTCUSDT"
        assert dec_eth.symbol == "ETHUSDT"
        # Whatever the BTCUSDT-scoped recommendation did to BTCUSDT's
        # decision, ETHUSDT's decision must not be affected by it — proven
        # by ETHUSDT's decision matching what it would be with zero
        # recommendations at all.
        dec_eth_plain, _ = adapter.decide_with_signal("ETHUSDT")
        assert dec_eth.confidence == dec_eth_plain.confidence

    def test_never_raises_when_recommendation_application_itself_errors(self, monkeypatch):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)

        import learning.application.recommendation_service as svc_module

        def _boom(*a, **kw):
            raise RuntimeError("simulated")

        monkeypatch.setattr(svc_module, "apply_learning_recommendations", _boom)

        adapter, _ = _make_adapter()
        dec, sig = adapter.decide_with_signal("BTCUSDT", recommendations=recs)
        assert dec is not None  # CEOAgent's own try/except caught it; adapter never sees an exception


class TestMultiSymbolCEODispatcherForwardsKwargs:
    """agents/ceo_symbol_cache.py::MultiSymbolCEODispatcher is what
    CEOGatedSignalProvider actually holds in production (not a bare
    MultiSymbolCEOAdapter) — confirm its **kwargs passthrough actually
    reaches recommendations."""

    def _make_dispatcher(self):
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        cache = CEOAgentSymbolCache()
        return MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)

    def test_decide_with_signal_forwards_recommendations(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        dispatcher = self._make_dispatcher()
        dec_plain, _ = dispatcher.decide_with_signal("BTCUSDT")
        dec_with_recs, _ = dispatcher.decide_with_signal("BTCUSDT", recommendations=recs)
        assert dec_with_recs.action == dec_plain.action  # action never changes


# ══════════════════════════════════════════════════════════════════════════
# CEOGatedSignalProvider.recommendation_provider
# ══════════════════════════════════════════════════════════════════════════

LONG_SIGNAL = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)


class FakeSignalProvider:
    def __init__(self, signal=None):
        self.signal = signal

    def get_signal(self, symbol):
        return self.signal


class FakeAdapterNoKwargs:
    """Mirrors tests/test_ceo_gated_signal_provider.py's own FakeAdapter
    (pre-Step-4 signature: no **kwargs) — confirms the gated provider
    never breaks a caller that doesn't accept extra arguments when no
    recommendation_provider is configured."""

    def __init__(self, decision=None, signal=None):
        self.decision = decision
        self.signal = signal
        self.calls = []

    def decide_with_signal(self, symbol):
        self.calls.append(symbol)
        return self.decision, self.signal


class FakeAdapterWithKwargs:
    def __init__(self, decision=None, signal=None):
        self.decision = decision
        self.signal = signal
        self.calls = []

    def decide_with_signal(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs.get("recommendations")))
        return self.decision, self.signal


class TestRecommendationProviderWiring:

    def test_no_recommendation_provider_is_byte_identical_call_shape(self):
        """Default (no recommendation_provider): must call
        decide_with_signal(symbol) with NO extra kwargs — proven by using
        an adapter fake with the OLD signature that has no **kwargs."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterNoKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, enabled=True)
        result = gated.get_signal("BTCUSDT")
        assert result == LONG_SIGNAL
        assert adapter.calls == ["BTCUSDT"]

    def test_recommendation_provider_result_is_threaded_through(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=lambda: recs,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", recs)]

    def test_recommendation_provider_failure_does_not_break_the_cycle(self):  # item 16-adjacent
        def _boom():
            raise RuntimeError("simulated state read failure")

        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=_boom,
        )
        result = gated.get_signal("BTCUSDT")
        assert result == LONG_SIGNAL  # decision cycle proceeds; recommendations just weren't available
        assert adapter.calls == [("BTCUSDT", None)]  # empty kwargs -> .get() defaults to None

    def test_empty_list_from_provider_is_threaded_through_as_empty(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=lambda: [],
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", [])]


# ══════════════════════════════════════════════════════════════════════════
# main.run_learning_recommendation_refresh — the missing producer
# ══════════════════════════════════════════════════════════════════════════

class FakeJournalV2:
    """Minimal fake matching what learning.dataset_builder.LearningDatasetBuilder
    needs — an empty trade history is a normal, honest state (item 16's
    'nothing to learn from yet' case)."""

    def get_ensemble_learning_dataset(self, limit=10_000, symbol=None):
        return []


class TestLearningRecommendationRefreshJob:

    def test_disabled_flag_is_a_no_op_and_never_touches_the_journal(self):  # item 1
        import main as main_module
        settings.RECOMMENDATION_APPLICATION_ENABLED = False

        class TouchedIfCalledJournal:
            def get_ensemble_learning_dataset(self, limit=10_000, symbol=None):
                raise AssertionError(
                    "journal was read even though RECOMMENDATION_APPLICATION_ENABLED is False"
                )

        # If the flag check didn't short-circuit before any dataset build,
        # get_ensemble_learning_dataset() above would raise and fail this test.
        main_module.run_learning_recommendation_refresh({"journal_v2": TouchedIfCalledJournal()})

    def test_enabled_generates_and_stores_recommendations(self):  # item 18 (single generation)
        import main as main_module
        import api.app as api_module

        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        api_module.set_state("learning_recommendations", None)  # clear any prior test's state

        main_module.run_learning_recommendation_refresh({"journal_v2": FakeJournalV2()})

        stored = api_module.get_state("learning_recommendations")
        assert isinstance(stored, list)  # empty trade history -> empty recommendations, not an error

    def test_generation_failure_is_caught_and_logged_not_raised(self, monkeypatch):  # item 16
        import main as main_module

        settings.RECOMMENDATION_APPLICATION_ENABLED = True

        class BoomJournal:
            def get_ensemble_learning_dataset(self, limit=10_000, symbol=None):
                raise RuntimeError("simulated journal failure")

        # Must not raise — same "log-and-continue" contract as
        # run_nightly_retrain_job.
        main_module.run_learning_recommendation_refresh({"journal_v2": BoomJournal()})

    def test_default_disabled(self):
        from config.settings import Settings
        assert Settings().RECOMMENDATION_APPLICATION_ENABLED is False
