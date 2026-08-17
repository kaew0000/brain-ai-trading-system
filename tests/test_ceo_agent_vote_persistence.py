"""
tests/test_ceo_agent_vote_persistence.py — V16 Phase 4C Step 7:
Per-Agent Vote Persistence for CEO-Gated Multi-Symbol Decisions.

Gap (confirmed by this phase's own fresh-clone audit): the real 6-agent
layer agents/ceo_symbol_cache.py::CEOAgentSymbolCache.get_ceo_agent()
builds per symbol (via agents/__init__.py::build_agent_layer()) DOES
run for every CEO-gated multi-symbol decision — CEODecision.agent_reports
and .weights_used are genuinely populated, not empty-by-construction.
(journal_v2.get_trade_attribution()'s docstring describing "the
pipeline doesn't run the agent layer" is accurate for the *plain*
execution/portfolio_signal_provider.py path, which never touches
CEOAgent at all — a different path from the one this phase covers.)
But execution/ceo_gated_signal_provider.py::_journal_ceo_decision()
only ever wrote ONE row (agent="CEO_AGENT") and never carried
agent_reports/weights_used at all — every individual sub-agent's vote
was computed, then discarded, every single decision cycle.

Scope (explicitly NOT the same as fixing get_trade_attribution()'s
agent_participation — see this phase's own PATCH_NOTES.md "Known
follow-up work"): this closes the DECISION-level observability gap
only — per-agent votes now inspectable per decision cycle via the
existing /api/ceo-decisions, same mechanism and same file Step 6 used
for recommendation_explanations. Closing the TRADE-level join
(trades.signal_id == agent_decisions.signal_id) is a separate,
larger, cross-layer piece of work this phase's audit found but did
not attempt.
"""
from __future__ import annotations

import pytest

from agents.ceo_agent import CEOAgent, CEODecision
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionSignal
from execution.portfolio_signal_provider import PortfolioSignalProvider
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit

LONG_SIGNAL = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)


class FakeSignalProviderUnused:
    def get_signal(self, symbol):
        raise AssertionError("outer signal_provider should not be called when CEO gating is enabled")


class FakeJournal:
    """Same minimal fake every other file in this test suite defines
    locally — no shared fixture, matching the established per-file
    convention."""

    def __init__(self, raise_on_save=False):
        self.saved = []
        self.raise_on_save = raise_on_save

    def save_agent_decision(self, **kwargs):
        if self.raise_on_save:
            raise RuntimeError("simulated DB failure")
        self.saved.append(kwargs)


def _make_real_dispatcher(trend="up"):
    """Real live chain — no fake adapter, per this project's own
    established live-path test convention (Steps 5/6)."""
    dp = FakeDataProvider(data_by_symbol={"BTCUSDT": _full_market_data(symbol="BTCUSDT", trend=trend, price=60000.0)})
    provider = PortfolioSignalProvider(data_provider=dp)
    cache = CEOAgentSymbolCache()
    return MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)


class TestAgentLayerGenuinelyRuns:
    """This phase's central audit finding, reasserted as a regression
    test: the CEO-gated path's agent_reports is NOT empty-by-
    construction — a future change to CEOAgentSymbolCache that broke
    this would silently make Step 7's whole premise false."""

    def test_agent_reports_populated_for_ceo_gated_multi_symbol_decision(self):
        dispatcher = _make_real_dispatcher()
        decision, _signal = dispatcher.decide_with_signal("BTCUSDT")
        assert isinstance(decision.agent_reports, dict)
        assert len(decision.agent_reports) > 0  # real sub-agents actually voted

    def test_weights_used_populated_for_ceo_gated_multi_symbol_decision(self):
        dispatcher = _make_real_dispatcher()
        decision, _signal = dispatcher.decide_with_signal("BTCUSDT")
        assert isinstance(decision.weights_used, dict)
        assert len(decision.weights_used) > 0


class TestLiveVotePersistence:

    def test_agent_reports_persist_to_journal_details(self):
        journal = FakeJournal()
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")

        # V16 Phase 4C Step 7C: CEO_AGENT row is always saved.saved[0] —
        # per-agent rows are appended after it (see
        # _journal_ceo_decision()), one per real sub-agent that voted.
        # Pre-Step-7C this asserted `== 1` (CEO_AGENT only, agent votes
        # were computed but discarded); now that they're persisted as
        # their own independently-inspectable rows (H3/H4), the count is
        # 1 + however many agents actually voted this cycle.
        assert len(journal.saved) >= 1
        details = journal.saved[0]["details"]
        assert "agent_reports" in details
        assert isinstance(details["agent_reports"], dict)
        assert len(details["agent_reports"]) > 0
        assert len(journal.saved) == 1 + len(details["agent_reports"])

    def test_weights_used_persist_to_journal_details(self):
        journal = FakeJournal()
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")

        details = journal.saved[0]["details"]
        assert "weights_used" in details
        assert isinstance(details["weights_used"], dict)

    def test_persisted_agent_reports_are_the_real_computed_reports(self):
        """Not a placeholder/summary — the actual per-agent report
        content (agent name keys, each a dict) survives into the
        journal untouched."""
        dispatcher = _make_real_dispatcher()
        decision, _signal = dispatcher.decide_with_signal("BTCUSDT")

        journal = FakeJournal()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        persisted = journal.saved[0]["details"]["agent_reports"]
        # same agent keys as a direct call produced (both went through
        # the same cached per-symbol CEOAgent, so the vote set matches)
        assert set(persisted.keys()) == set(decision.agent_reports.keys())
        for agent_name, report in persisted.items():
            assert isinstance(report, dict)

    def test_json_serializable(self):
        import json

        journal = FakeJournal()
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        json.dumps(journal.saved[0]["details"])  # must not raise


class TestExistingFieldsUnaffected:
    """Step 6's own recommendation_explanations, and the pre-Step-6
    reasons/agreement_score/direction fields, must be completely
    unaffected by this additive change — same file, same dict, same
    method."""

    def test_recommendation_explanations_still_present_and_correct(self):
        journal = FakeJournal()
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        details = journal.saved[0]["details"]
        assert details["recommendation_explanations"] == []  # no recommendation_provider configured -> empty, unchanged

    def test_reasons_agreement_score_direction_still_present(self):
        journal = FakeJournal()
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        details = journal.saved[0]["details"]
        assert "reasons" in details
        assert "agreement_score" in details
        assert "direction" in details


class TestFailureIsolation:

    def test_journal_write_failure_does_not_break_signal_cycle(self):
        journal = FakeJournal(raise_on_save=True)
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")  # must not raise


class TestBackwardCompatibility:

    def test_no_journal_configured_is_a_no_op(self):
        dispatcher = _make_real_dispatcher()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, execution_lane="LIVE", journal=None, enabled=True)
        gated.get_signal("BTCUSDT")  # must not raise with journal=None

    def test_ceodecision_agent_reports_default_unaffected(self):
        """CEODecision's own pre-existing agent_reports field (present
        since before this phase) has an unchanged default."""
        d = CEODecision(action="LONG", confidence=80.0)
        assert d.agent_reports == {}

    def test_empty_agents_ceoagent_produces_no_error(self):
        """A CEOAgent constructed with no sub-agents (agents={}) — the
        genuinely-empty case journal_v2.get_trade_attribution()'s
        docstring describes for a DIFFERENT path — must still journal
        cleanly with an empty agent_reports, not error."""
        ceo = CEOAgent(agents={})
        journal = FakeJournal()

        class _DirectAdapter:
            def decide_with_signal(self, symbol, **kwargs):
                decision = ceo.decide({"symbol": symbol, "regime": "TRENDING"})
                return decision, None

        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), _DirectAdapter(), execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        assert journal.saved[0]["details"]["agent_reports"] == {}
