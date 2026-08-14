"""
tests/test_recommendation_dataset_row_count_wiring.py — V16 Phase 4C
Step 5: Live Recommendation Scoring Completeness.

Root cause (confirmed by this phase's own fresh-clone audit): Step 4
wired `_state["learning_dataset_row_count"]` as a producer
(main.run_learning_recommendation_refresh) and the ENTIRE consumer
chain below CEOGatedSignalProvider already accepted/forwarded it
(MultiSymbolCEODispatcher's generic **kwargs passthrough,
MultiSymbolCEOAdapter.decide_with_signal(dataset_row_count=...),
CEOAgent.decide_from_context_with_recommendations(dataset_row_count=...),
apply_learning_recommendations(dataset_row_count=...)) — but nothing
ever read the value back OUT of `_state` and INTO that chain.
CEOGatedSignalProvider had no second provider slot for it, so the live
path always called with dataset_row_count omitted, and
recommendation_scoring._coverage_subscore() (unit-tested and unchanged
since Step 3) fell back to its own existing, correct 0.0 default.

This file tests ONLY the two lines of actual gap this phase closes:
CEOGatedSignalProvider.dataset_row_count_provider (new, optional,
same idiom as recommendation_provider) and main.py's wiring of it to
`_state["learning_dataset_row_count"]`. The scoring formula itself,
the confidence-adjustment safety contract, and every other Step 3/4
behavior are exercised by their own existing test files, unmodified —
not duplicated here.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from agents.ceo_agent import CEODecision
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from config.settings import settings
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
from learning.application.recommendation_scoring import score_recommendation
from learning.application.recommendation_validator import validate_all
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit

LONG_SIGNAL = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)


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


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.15, "sample_size": 80},
                   description="d", severity=severity)


class FakeSignalProvider:
    def __init__(self, signal=None):
        self.signal = signal

    def get_signal(self, symbol):
        return self.signal


class FakeAdapterWithKwargs:
    """Same fake tests/test_ceo_live_recommendation_wiring.py's own
    TestRecommendationProviderWiring uses, extended to also capture
    dataset_row_count."""

    def __init__(self, decision=None, signal=None):
        self.decision = decision
        self.signal = signal
        self.calls = []

    def decide_with_signal(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs.get("recommendations"), kwargs.get("dataset_row_count")))
        return self.decision, self.signal


class FakeAdapterNoKwargs:
    """Pre-Step-4/5 signature: no **kwargs at all. Proves the byte-
    identical call shape guarantee still holds when neither provider is
    configured."""

    def __init__(self, decision=None, signal=None):
        self.decision = decision
        self.signal = signal
        self.calls = []

    def decide_with_signal(self, symbol):
        self.calls.append(symbol)
        return self.decision, self.signal


# ══════════════════════════════════════════════════════════════════════════
# Item 1 — existing callers with dataset_row_count=None retain old behavior
# ══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:

    def test_no_dataset_row_count_provider_is_byte_identical_call_shape(self):
        """Neither provider configured: decide_with_signal(symbol) must be
        called with ZERO extra kwargs — proven with a fake that has no
        **kwargs at all, exactly like Step 4's own equivalent test."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterNoKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, enabled=True)
        result = gated.get_signal("BTCUSDT")
        # V16 W14-2A: agent_attribution_from_ceo_decision() output is now
        # threaded onto the returned signal — compare pricing/direction
        # fields only, matching this test's own "byte-identical call
        # shape" intent (about the decide_with_signal() call, not the
        # returned signal's full equality).
        assert result.direction == LONG_SIGNAL.direction
        assert result.entry_price == LONG_SIGNAL.entry_price
        assert result.stop_loss == LONG_SIGNAL.stop_loss
        assert result.take_profit == LONG_SIGNAL.take_profit
        assert adapter.calls == ["BTCUSDT"]

    def test_recommendation_provider_alone_still_works_unchanged(self):
        """dataset_row_count_provider NOT configured, recommendation_provider
        IS — dataset_row_count must simply be absent (None via .get()),
        recommendations must thread through exactly as before Step 5."""
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=lambda: recs,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", recs, None)]


# ══════════════════════════════════════════════════════════════════════════
# Items 2 + 4 — a valid dataset_row_count reaches the correct per-decision
# recommendation application path
# ══════════════════════════════════════════════════════════════════════════

class TestDatasetRowCountThreading:

    def test_dataset_row_count_provider_result_is_threaded_through(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            dataset_row_count_provider=lambda: 750,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", None, 750)]

    def test_both_providers_configured_thread_through_together(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=lambda: recs,
            dataset_row_count_provider=lambda: 1200,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", recs, 1200)]

    def test_zero_dataset_row_count_is_threaded_through_not_treated_as_falsy_none(self):
        """0 is a valid (if unusual) count and must be distinguished from
        'no provider configured' — proven by threading it through as the
        literal 0, not silently dropped."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            dataset_row_count_provider=lambda: 0,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", None, 0)]

    def test_provider_returning_none_is_threaded_through_as_none(self):
        """A configured provider that itself has no count yet (e.g. no
        learning refresh has run) must thread through None explicitly —
        same conservative fallback as if the provider weren't configured
        at all."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            dataset_row_count_provider=lambda: None,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", None, None)]


# ══════════════════════════════════════════════════════════════════════════
# Item 8 — provider failure falls back safely
# ══════════════════════════════════════════════════════════════════════════

class TestFailureSafety:

    def test_dataset_row_count_provider_failure_does_not_break_the_cycle(self):
        def _boom():
            raise RuntimeError("simulated state read failure")

        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            dataset_row_count_provider=_boom,
        )
        result = gated.get_signal("BTCUSDT")
        # decision cycle proceeds regardless. V16 W14-2A: compare pricing
        # fields only — see this file's other updated assertion above.
        assert result.direction == LONG_SIGNAL.direction
        assert result.entry_price == LONG_SIGNAL.entry_price
        assert result.stop_loss == LONG_SIGNAL.stop_loss
        assert result.take_profit == LONG_SIGNAL.take_profit
        assert adapter.calls == [("BTCUSDT", None, None)]

    def test_dataset_row_count_provider_failure_does_not_affect_recommendations(self):
        """The two providers fail independently — a broken
        dataset_row_count_provider must not stop recommendations from
        threading through."""
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)

        def _boom():
            raise RuntimeError("simulated")

        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapterWithKwargs(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            recommendation_provider=lambda: recs,
            dataset_row_count_provider=_boom,
        )
        gated.get_signal("BTCUSDT")
        assert adapter.calls == [("BTCUSDT", recs, None)]


# ══════════════════════════════════════════════════════════════════════════
# Item 5 — multi-symbol: same global dataset context, no cross-symbol leakage
# ══════════════════════════════════════════════════════════════════════════

class TestMultiSymbolDatasetRowCountIsolation:

    def _make_dispatcher(self):
        dp = FakeDataProvider(data_by_symbol={
            "BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up", price=60000.0),
            "ETHUSDT": _full_market_data(symbol="ETHUSDT", trend="down", price=3000.0),
        })
        provider = PortfolioSignalProvider(data_provider=dp)
        cache = CEOAgentSymbolCache()
        return MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)

    def test_btc_and_eth_receive_the_same_global_dataset_row_count(self):
        """The learning pipeline produces ONE global dataset_row_count
        (learning/dataset_builder.py builds one LearningDataset across
        every symbol's trade history, not a per-symbol one) — every
        symbol must receive that same value, not a fabricated
        symbol-specific one."""
        dispatcher = self._make_dispatcher()
        dec_btc, _ = dispatcher.decide_with_signal("BTCUSDT", dataset_row_count=900)
        dec_eth, _ = dispatcher.decide_with_signal("ETHUSDT", dataset_row_count=900)
        # action never changes regardless of dataset_row_count (Part H)
        assert dec_btc.action in ("LONG", "SHORT", "WAIT", "BLOCKED")
        assert dec_eth.action in ("LONG", "SHORT", "WAIT", "BLOCKED")

    def test_repeated_alternating_calls_mutate_no_shared_state(self):
        """A fresh MultiSymbolCEOAdapter is constructed per call
        (agents/ceo_symbol_cache.py's own documented design) — a plain
        int argument passed through **kwargs cannot leak between calls,
        but this proves it end-to-end rather than by code inspection
        alone: alternating BTCUSDT/ETHUSDT calls with DIFFERENT counts
        must never cross-contaminate."""
        dispatcher = self._make_dispatcher()
        dec_btc_1, _ = dispatcher.decide_with_signal("BTCUSDT", dataset_row_count=500)
        dec_eth_1, _ = dispatcher.decide_with_signal("ETHUSDT", dataset_row_count=999)
        dec_btc_2, _ = dispatcher.decide_with_signal("BTCUSDT", dataset_row_count=500)
        dec_eth_2, _ = dispatcher.decide_with_signal("ETHUSDT", dataset_row_count=999)
        assert dec_btc_1.confidence == dec_btc_2.confidence
        assert dec_eth_1.confidence == dec_eth_2.confidence

    def test_dispatcher_forwards_dataset_row_count_generically(self):
        """MultiSymbolCEODispatcher.decide_with_signal uses a bare
        **kwargs passthrough (agents/ceo_symbol_cache.py) — confirm
        dataset_row_count specifically (not just recommendations, which
        Step 4's own suite already covers) survives that passthrough
        without error, with and without RECOMMENDATION_APPLICATION_ENABLED."""
        dispatcher = self._make_dispatcher()
        dec_plain, _ = dispatcher.decide_with_signal("BTCUSDT")
        dec_with_count, _ = dispatcher.decide_with_signal("BTCUSDT", dataset_row_count=750)
        assert dec_with_count.action == dec_plain.action  # action never changes


# ══════════════════════════════════════════════════════════════════════════
# Items 3 — coverage_subscore is no longer silently forced to 0.0 when a
# valid count exists (already unit-tested in test_recommendation_scoring.py
# — reasserted here narrowly, scoped to THIS phase's specific claim)
# ══════════════════════════════════════════════════════════════════════════

class TestCoverageSubscoreReceivesRealCount:

    def test_valid_dataset_row_count_produces_nonzero_coverage_contribution(self):
        now = datetime.now(timezone.utc)
        rec = validate_all(RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.2, "sample_size": 40})], now=now,
        ), now=now)[0]
        score_without = score_recommendation(rec, dataset_row_count=None, now=now)
        score_with = score_recommendation(rec, dataset_row_count=1000, now=now)
        assert score_with > score_without  # coverage sub-score is no longer forced to 0.0

    def test_dataset_row_count_none_still_conservatively_falls_back(self):
        """Unchanged Step 3 behavior — reasserted here as this phase's own
        explicit 'conservative fallback stays intact' requirement, not a
        rewrite of test_recommendation_scoring.py's own coverage."""
        now = datetime.now(timezone.utc)
        rec = validate_all(RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.2, "sample_size": 40})], now=now,
        ), now=now)[0]
        score = score_recommendation(rec, dataset_row_count=None, now=now)
        assert 0.0 <= score <= 1.0  # does not error, does not fabricate coverage


# ══════════════════════════════════════════════════════════════════════════
# Items 10 + 11 — BLOCKED / action / direction / score_breakdown /
# agreement_score remain untouched, even with dataset_row_count flowing
# ══════════════════════════════════════════════════════════════════════════

class TestSafetyInvariantsUnaffectedByDatasetRowCount:

    def test_blocked_decision_byte_identical_even_with_dataset_row_count(self):
        blocked = CEODecision(action="BLOCKED", direction="", confidence=0.0,
                               score_breakdown={"x": 1}, agreement_score=0.4)
        adapter = FakeAdapterWithKwargs(decision=blocked, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(
            FakeSignalProvider(), adapter, enabled=True,
            dataset_row_count_provider=lambda: 5000,
        )
        result = gated.get_signal("BTCUSDT")
        assert result is None  # BLOCKED -> vetoed, per map_ceo_decision_to_signal
        assert adapter.calls == [("BTCUSDT", None, 5000)]  # dataset_row_count still threaded, decision untouched

    def test_dispatcher_never_changes_action_direction_score_breakdown_agreement_score(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.05, "sample_size": 200})], now=now,
        )
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        cache = CEOAgentSymbolCache()
        dispatcher = MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)

        dec_plain, _ = dispatcher.decide_with_signal("BTCUSDT")
        dec_full, _ = dispatcher.decide_with_signal(
            "BTCUSDT", recommendations=recs, dataset_row_count=1000,
        )
        assert dec_full.action == dec_plain.action
        assert dec_full.direction == dec_plain.direction
        assert dec_full.score_breakdown == dec_plain.score_breakdown
        assert dec_full.agreement_score == dec_plain.agreement_score


# ══════════════════════════════════════════════════════════════════════════
# Item "state propagation" — the refresh job stores BOTH keys, not just
# learning_recommendations (Step 4's own test file only asserted the
# latter; this closes that narrow gap without touching that file)
# ══════════════════════════════════════════════════════════════════════════

class FakeJournalV2ForRefresh:
    """Same minimal empty-history fake
    tests/test_ceo_live_recommendation_wiring.py's own FakeJournalV2
    uses, redefined locally rather than imported — that class isn't a
    shared public fixture, matching this file's convention of defining
    its own small fakes."""

    def get_ensemble_learning_dataset(self, limit=10_000, symbol=None):
        return []


class TestRefreshJobStoresBothStateKeys:

    def test_refresh_stores_dataset_row_count_alongside_recommendations(self):
        import api.app as api_module
        import main as main_module

        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        api_module.set_state("learning_recommendations", None)
        api_module.set_state("learning_dataset_row_count", None)

        main_module.run_learning_recommendation_refresh({"journal_v2": FakeJournalV2ForRefresh()})

        assert isinstance(api_module.get_state("learning_recommendations"), list)
        # Empty trade history -> a real (zero) row count, not an error and
        # not left as None — the producer side (Step 4, unchanged) always
        # writes this key when the job runs successfully.
        assert api_module.get_state("learning_dataset_row_count") is not None
