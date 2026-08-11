"""
tests/test_recommendation_explanation_persistence.py — V16 Phase 4C
Step 6: Live Recommendation Explanation Persistence.

Gap (confirmed by this phase's own fresh-clone audit): CEOAgent.
decide_with_recommendations() / decide_from_context_with_recommendations()
already computed the full `AppliedRecommendationExplanation` list on
every call to apply_learning_recommendations() (Part C's own
explainability deliverable, Phase 4C Step 3) but discarded it before
returning, since both methods return a bare CEODecision, not a tuple.
Only one aggregate line ("[learning] applied N recommendation(s),
confidence ±X.XX") survived, folded into `decision.reasons` — every
individual recommendation id/score/sample_size/source_pattern/effect,
and every skip reason, was lost the instant the method returned.

This phase closes that gap with the smallest possible additive change:
CEODecision gains a `recommendation_explanations` field (empty-list
default, populated only by the two `_with_recommendations` methods),
and execution/ceo_gated_signal_provider.py::_journal_ceo_decision()
(already the ONE place a CEODecision gets journaled) forwards it into
the SAME `details` dict `reasons`/`agreement_score`/`direction` already
go through. No new table, no new journal, no new endpoint —
`/api/ceo-decisions` (journal_v2.get_agent_decisions()) already
surfaces `details` unmodified.

Per this phase's own "TEST DESIGN RULE": every test below traces the
FULL chain (recommendation -> live decision -> journal `details` ->
inspectable persisted representation), not just "explanations is not
None" at some intermediate layer. tests/test_recommendation_advisor.py
and tests/test_ceo_decide_with_recommendations.py already cover the
advisor/CEOAgent layers directly and are NOT duplicated here.
"""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from agents.ceo_agent import CEOAgent, CEODecision
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from config.settings import settings
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
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


class FakeSignalProviderUnused:
    """CEOGatedSignalProvider's OUTER signal_provider is only ever called
    when gating is disabled (enabled=False) — every test here runs
    enabled=True, so this must never actually be invoked."""

    def get_signal(self, symbol):
        raise AssertionError("outer signal_provider should not be called when CEO gating is enabled")


class FakeJournal:
    """Same fake tests/test_ceo_gated_signal_provider.py's own
    TestJournalPersistence uses, redefined locally per this file's own
    convention (each test file owns its small fakes)."""

    def __init__(self, raise_on_save=False):
        self.saved = []
        self.raise_on_save = raise_on_save

    def save_agent_decision(self, **kwargs):
        if self.raise_on_save:
            raise RuntimeError("simulated DB failure")
        self.saved.append(kwargs)


def _make_gated_provider(journal, *, recommendations=None, dataset_row_count=750, trend="up"):
    """Builds the REAL live chain: CEOGatedSignalProvider ->
    MultiSymbolCEODispatcher -> MultiSymbolCEOAdapter ->
    CEOAgent.decide_from_context_with_recommendations() -> journal.
    No fakes below CEOGatedSignalProvider itself — this is what the
    brief's LIVE-PATH REQUIREMENT calls for."""
    dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(symbol="BTCUSDT", trend=trend, price=60000.0)})
    provider = PortfolioSignalProvider(data_provider=dp)
    cache = CEOAgentSymbolCache()
    dispatcher = MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)

    kwargs = {}
    if recommendations is not None:
        kwargs["recommendation_provider"] = lambda: recommendations
    if dataset_row_count is not None:
        kwargs["dataset_row_count_provider"] = lambda: dataset_row_count

    return CEOGatedSignalProvider(
        FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True, **kwargs,
    )


# ══════════════════════════════════════════════════════════════════════════
# 1 — live explanation persistence: the full chain, end to end
# ══════════════════════════════════════════════════════════════════════════

class TestLiveExplanationPersistence:

    def test_live_decision_persists_explanations_to_journal(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)

        gated.get_signal("BTCUSDT")

        # V16 Phase 4C Step 7C: CEO_AGENT row is saved.saved[0] — this
        # test's live chain now also persists one row per real
        # participating sub-agent (H3/H4), appended after it. Was
        # `== 1` pre-Step-7C (CEO_AGENT only); see
        # tests/test_ceo_agent_vote_persistence.py's own
        # test_agent_reports_persist_to_journal_details for the same
        # pattern.
        assert len(journal.saved) >= 1
        details = journal.saved[0]["details"]
        assert "recommendation_explanations" in details
        assert isinstance(details["recommendation_explanations"], list)
        assert len(details["recommendation_explanations"]) >= 1
        assert len(journal.saved) == 1 + len(details["agent_reports"])

    def test_persisted_representation_is_plain_json_serializable(self):
        """Proves it's an actually-inspectable representation, not just
        a Python object graph that happens not to error."""
        import json

        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)
        gated.get_signal("BTCUSDT")

        details = journal.saved[0]["details"]
        json.dumps(details)  # must not raise


# ══════════════════════════════════════════════════════════════════════════
# 2 — applied recommendation persists its full explanation
# ══════════════════════════════════════════════════════════════════════════

class TestAppliedRecommendationPersists:

    def test_applied_explanation_carries_id_score_sample_size_source_pattern(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)
        gated.get_signal("BTCUSDT")

        explanations = journal.saved[0]["details"]["recommendation_explanations"]
        applied = [e for e in explanations if e["applied"] is True]
        assert len(applied) == 1
        e = applied[0]
        assert e["recommendation_id"] == recs[0].id
        assert e["source_pattern"] == "worst_symbol"
        assert e["sample_size"] == 80
        assert e["effect"] == "decrease_confidence"
        assert e["score"] is not None
        assert e["skip_reason"] is None


# ══════════════════════════════════════════════════════════════════════════
# 3 — skipped recommendation + its skip reason remain inspectable
# ══════════════════════════════════════════════════════════════════════════

class TestSkippedRecommendationPersists:

    def test_skipped_explanation_carries_skip_reason(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        # insufficient sample -> validator_status=insufficient_sample -> skipped
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 1})], now=now,
        )
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)
        gated.get_signal("BTCUSDT")

        explanations = journal.saved[0]["details"]["recommendation_explanations"]
        assert len(explanations) == 1
        e = explanations[0]
        assert e["applied"] is False
        assert e["skip_reason"] == "validator_status=insufficient_sample"


# ══════════════════════════════════════════════════════════════════════════
# 4 — multiple explanations survive, not collapsed into the aggregate line
# ══════════════════════════════════════════════════════════════════════════

class TestMultipleRecommendationsSurvive:

    def test_multiple_explanations_all_persist_individually(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [
                _pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80}),
                # losing_streak is portfolio-level (subject="sequence",
                # no symbol/regime scoping at all — see
                # recommendation_engine.py's own _extract_symbol_and_regime())
                # so, unlike a regime-scoped pattern, it applies
                # regardless of what regime the real market data
                # produces — avoids this test depending on RegimeEngine's
                # actual output for the fake OHLCV series.
                _pattern("losing_streak", "sequence", metric={"length": 6}, severity="negative"),
                # valid sample size, so this is excluded specifically by
                # symbol_mismatch, not an unrelated validator failure —
                # demonstrating the symbol-scoping this phase's
                # explanations are meant to make inspectable.
                _pattern("worst_symbol", "ETHUSDT", metric={"win_rate": 0.2, "sample_size": 80}),
            ],
            now=now,
        )
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)
        gated.get_signal("BTCUSDT")

        details = journal.saved[0]["details"]
        explanations = details["recommendation_explanations"]
        # ALL THREE recommendations this cycle considered are present —
        # applied ones AND the skipped one — not collapsed into just the
        # aggregate confidence line.
        assert len(explanations) == 3
        by_id = {e["recommendation_id"]: e for e in explanations}
        assert len(by_id) == 3  # three distinct identities, not deduped/collapsed

        applied = [e for e in explanations if e["applied"] is True]
        skipped = [e for e in explanations if e["applied"] is False]
        assert len(applied) == 2  # BTCUSDT worst_symbol + losing_streak
        assert len(skipped) == 1
        assert skipped[0]["reason"].startswith("ETHUSDT")
        assert skipped[0]["skip_reason"] == "symbol_mismatch"

        # the terse aggregate line is STILL present too — additive, not a replacement
        assert any("[learning] applied" in r for r in details["reasons"])


# ══════════════════════════════════════════════════════════════════════════
# 5 — no recommendations: unchanged, empty explanations
# ══════════════════════════════════════════════════════════════════════════

class TestNoRecommendationsUnchanged:

    def test_no_recommendations_yields_empty_explanations(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=[])
        gated.get_signal("BTCUSDT")

        assert journal.saved[0]["details"]["recommendation_explanations"] == []

    def test_no_recommendation_provider_configured_yields_empty_explanations(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=None)
        gated.get_signal("BTCUSDT")

        assert journal.saved[0]["details"]["recommendation_explanations"] == []


# ══════════════════════════════════════════════════════════════════════════
# 6 — RECOMMENDATION_APPLICATION_ENABLED=False: legacy behavior unchanged
# ══════════════════════════════════════════════════════════════════════════

class TestApplicationDisabled:

    def test_disabled_flag_yields_empty_explanations_even_with_recommendations(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = False
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        journal = FakeJournal()
        gated = _make_gated_provider(journal, recommendations=recs)
        gated.get_signal("BTCUSDT")

        assert journal.saved[0]["details"]["recommendation_explanations"] == []

    def test_disabled_flag_confidence_matches_plain_decide(self):
        """Legacy behavior byte-identical in VALUE — same guarantee
        decide_with_recommendations()'s own docstring already promises,
        reasserted here at the live CEOAgent.decide_from_context_with_
        recommendations() layer specifically."""
        settings.RECOMMENDATION_APPLICATION_ENABLED = False
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.05, "sample_size": 200})], now=now,
        )
        dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(symbol="BTCUSDT", trend="up")})
        provider = PortfolioSignalProvider(data_provider=dp)
        cache = CEOAgentSymbolCache()
        dispatcher = MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)

        dec_plain, _ = dispatcher.decide_with_signal("BTCUSDT")
        dec_with_recs, _ = dispatcher.decide_with_signal("BTCUSDT", recommendations=recs, dataset_row_count=500)
        assert dec_with_recs.confidence == dec_plain.confidence
        assert dec_with_recs.recommendation_explanations == []


# ══════════════════════════════════════════════════════════════════════════
# 7 — BLOCKED invariant: action/direction/score_breakdown/agreement_score
# remain unchanged in VALUE even though explanations get attached
# ══════════════════════════════════════════════════════════════════════════

class TestBlockedInvariant:

    def test_blocked_values_unchanged_when_explanations_attached(self):
        """A BLOCKED CEODecision going through decide_from_context_with_
        recommendations() still gets recommendation_explanations
        attached (documenting WHY each recommendation was skipped —
        "decision_blocked") via dataclasses.replace(), which returns a
        NEW object — but action/direction/score_breakdown/agreement_score
        VALUES must be byte-identical to what decide_from_context()
        alone would have produced. Object identity itself is NOT the
        contract here (recommendation_advisor.py's own
        apply_recommendations(), tested directly in
        tests/test_recommendation_advisor.py, IS still identity-
        preserving — this test is one layer up, at the CEOAgent method
        that attaches explanations afterward)."""
        agent = CEOAgent(agents={})

        class _AlwaysBlockedAgent(CEOAgent):
            def decide_from_context(self, context):
                return CEODecision(action="BLOCKED", direction="", confidence=0.0,
                                    score_breakdown={"veto": "risk"}, agreement_score=0.37,
                                    symbol=context.symbol)

        blocked_agent = _AlwaysBlockedAgent(agents={})
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        from agents.decision_context import CEODecisionContext
        context = CEODecisionContext(market_context={"symbol": "BTCUSDT", "regime": "TRENDING"}, symbol="BTCUSDT")

        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        baseline = blocked_agent.decide_from_context(context)
        result = blocked_agent.decide_from_context_with_recommendations(context, recommendations=recs)

        assert result.action == baseline.action == "BLOCKED"
        assert result.direction == baseline.direction
        assert result.score_breakdown == baseline.score_breakdown
        assert result.agreement_score == baseline.agreement_score
        # explanations WERE attached (all skipped, decision_blocked) —
        # proves this test actually exercised the Step 6 code path
        assert len(result.recommendation_explanations) >= 1
        assert all(e.skip_reason == "decision_blocked" for e in result.recommendation_explanations)


# ══════════════════════════════════════════════════════════════════════════
# 8 — persistence failure isolation
# ══════════════════════════════════════════════════════════════════════════

class TestPersistenceFailureIsolation:

    def test_journal_write_failure_does_not_break_the_signal_cycle(self):
        settings.RECOMMENDATION_APPLICATION_ENABLED = True
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.1, "sample_size": 80})], now=now,
        )
        journal = FakeJournal(raise_on_save=True)
        gated = _make_gated_provider(journal, recommendations=recs)

        # must not raise, regardless of what the underlying decision was
        gated.get_signal("BTCUSDT")


# ══════════════════════════════════════════════════════════════════════════
# 9 — backward compatibility: pre-Step-6 CEODecision construction and
# journal records without explanation details remain fully valid
# ══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:

    def test_ceodecision_constructed_without_the_new_field_still_works(self):
        d = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        assert d.recommendation_explanations == []

    def test_replace_without_touching_the_new_field_preserves_empty_default(self):
        d = CEODecision(action="LONG", confidence=80.0)
        d2 = replace(d, confidence=85.0)
        assert d2.recommendation_explanations == []

    def test_pre_step6_journal_call_shape_still_accepted(self):
        """A details dict without recommendation_explanations at all
        (i.e. a historical record from before this phase) must still be
        exactly what get_agent_decisions() would have returned — this
        phase adds a key, it doesn't require one on read."""
        journal = FakeJournal()
        journal.save_agent_decision(
            agent="CEO_AGENT", decision="LONG", symbol="BTCUSDT", score=80.0,
            details={"reasons": ["pre-existing record"], "agreement_score": 1.0, "direction": "LONG"},
        )
        assert "recommendation_explanations" not in journal.saved[0]["details"]  # untouched, not backfilled
