"""tests/test_ceo_vote_persistence_lifecycle.py — V16 §76.

ROADMAP "Planned" claimed that per-agent votes for CEO-gated multi-symbol
trades are not persisted, so the Learning Pipeline and per-agent outcome
attribution cannot see who voted how on the path that drives live
multi-symbol decisions. Reproduced against main @ 98088ca: that is not
true. The votes are written at decision time (Phase 4C Step 7 / Step 7C,
PRs #48/#51), threaded onto the trade as explicit attribution (W14-2A,
PR #54), and reach get_ensemble_learning_dataset(), LearningDatasetBuilder
and compute_agent_statistics() intact after the trade closes.

These tests lock that whole open -> close -> learning-dataset flow end to
end so it cannot silently regress. They PASS on main by design — there
is nothing to fix; §76 is documentation plus this regression lock.

What is real: the 6-agent layer (CEOAgentSymbolCache / MultiSymbolCEO-
Dispatcher / CEOAgent.decide), CEOGatedSignalProvider's journaling,
ExecutionOrchestrator.execute(), TradeLifecycle.exit_confirmed(),
TradeJournalV2 (tmp SQLite, real schema), the learning/ package.

What is controlled: the fixture market data always yields a WAIT (see
tests/test_ceo_multi_symbol_agent_attribution.py's module docstring), so
the one decision this module computes with the live agent layer is
re-labelled LONG via dataclasses.replace() before it is fed to the
provider. agent_reports / weights_used stay the REAL output of the live
agent layer for that cycle; only action/direction/confidence change.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import replace

import pytest

from agents.ceo_agent import CEOAgent
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from events.event_bus import reset_event_bus
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionOrchestrator, ExecutionSignal
from execution.execution_state import ExecutionState
from execution.portfolio_signal_provider import PortfolioSignalProvider
from execution.trade_lifecycle import CloseSource
from journal.journal_v2 import TradeJournalV2
from learning.agent_statistics import compute_agent_statistics
from learning.dataset_builder import LearningDatasetBuilder
from portfolio.portfolio_state import PortfolioState
from tests.test_execution_orchestrator import FakeEngine, FakePortfolioManager, make_allocation, make_decision
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit

SYMBOL = "BTCUSDT"
WEIGHTED_KEYS = set(CEOAgent.WEIGHTS)


# ── builders ────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolated_event_bus():
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
def journal(tmp_path):
    return TradeJournalV2(db_path=str(tmp_path / "journal.db"))


def _live_dispatcher():
    dp = FakeDataProvider(data_by_symbol={SYMBOL: _full_market_data(symbol=SYMBOL, trend="up", price=60000.0)})
    return MultiSymbolCEODispatcher(
        signal_provider=PortfolioSignalProvider(data_provider=dp), ceo_agent_cache=CEOAgentSymbolCache(),
    )


@pytest.fixture(scope="module")
def live_decision():
    """ONE real CEODecision from the live 6-agent layer (computed once per
    module — the per-symbol HMM fit makes it the slow part). Action is WAIT
    here; tests that need a confirmed trade re-label it via _confirmed()."""
    reset_event_bus()
    decision, _ = _live_dispatcher().decide_with_signal(SYMBOL)
    reset_event_bus()
    return decision


def _confirmed(decision):
    return replace(decision, action="LONG", direction="LONG", confidence=85.0)


class _Adapter:
    def __init__(self, decision):
        self.decision = decision

    def decide_with_signal(self, symbol, **kwargs):
        return self.decision, ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)


class _OuterUnused:
    def get_signal(self, symbol):
        raise AssertionError("outer provider must not be called when CEO gating is enabled")


class _NoExplicitAttribution(CEOGatedSignalProvider):
    """Same provider minus the W14-2A explicit agent_attribution, to exercise
    the Step 7C agent_decisions join (the pre-W14-2A shape)."""

    def get_signal(self, symbol):
        sig = super().get_signal(symbol)
        return replace(sig, agent_attribution=None) if sig is not None else sig


def _open_and_close(journal, decision, provider_cls=CEOGatedSignalProvider):
    """Open one CEO-gated trade through the real orchestrator, then close it
    as a WIN through the real TradeLifecycle. Returns (trade_id, signal_id)."""
    gated = provider_cls(_OuterUnused(), _Adapter(decision), execution_lane="LIVE", journal=journal, enabled=True)
    orch = ExecutionOrchestrator(
        execution_lane="LIVE", execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
        signal_provider=gated, state=ExecutionState(), journal=journal,
    )
    pstate = PortfolioState()
    orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)
    trade_id = pstate.get_position(SYMBOL).trade_id

    handle = orch.lifecycle.request_exit(SYMBOL, CloseSource.TAKE_PROFIT, "tp_hit", trade_id=trade_id)
    orch.lifecycle.exit_executing(handle)
    orch.lifecycle.exit_confirmed(handle, result="WIN", exit_price=110.0, pnl=10.0)

    conn = sqlite3.connect(journal.db_path)
    try:
        signal_id = conn.execute("SELECT signal_id FROM trades WHERE id=?", (trade_id,)).fetchone()[0]
    finally:
        conn.close()
    return trade_id, signal_id


def _decision_rows(journal, signal_id):
    return [r for r in journal.get_agent_decisions(limit=500) if r["signal_id"] == signal_id]


def _explicit_attribution(journal, trade_id):
    conn = sqlite3.connect(journal.db_path)
    try:
        raw = conn.execute("SELECT extra_data FROM trades WHERE id=?", (trade_id,)).fetchone()[0]
    finally:
        conn.close()
    return json.loads(raw)["attribution"].get("agent_attribution", [])


# ══════════════════════════════════════════════════════════════════════════
# 1. The live agent layer really produces votes (precondition for the rest)
# ══════════════════════════════════════════════════════════════════════════

class TestLiveAgentLayerProducesVotes:

    def test_every_weighted_agent_reports_and_weights_are_populated(self, live_decision):
        assert WEIGHTED_KEYS <= set(live_decision.agent_reports)
        assert set(live_decision.weights_used) == WEIGHTED_KEYS


# ══════════════════════════════════════════════════════════════════════════
# 2. Decision time: one journal row per agent, sharing the cycle's signal_id
# ══════════════════════════════════════════════════════════════════════════

class TestVotesPersistedAtDecisionTime:

    def test_wait_cycle_through_the_real_chain_persists_every_agent_vote(self, journal, live_decision):
        """No forcing at all: the real dispatcher's own WAIT cycle."""
        gated = CEOGatedSignalProvider(
            _OuterUnused(), _live_dispatcher(), execution_lane="LIVE", journal=journal, enabled=True,
        )
        assert gated.get_signal(SYMBOL) is None  # WAIT -> no signal, but still journaled for audit

        rows = journal.get_agent_decisions(limit=500)
        by_agent = {r["agent"]: r for r in rows}
        assert {"CEO_AGENT"} | set(live_decision.agent_reports) == set(by_agent)
        assert len({r["signal_id"] for r in rows}) == 1 and rows[0]["signal_id"] is not None
        # Each row's own details carry the AgentReport it was written from —
        # compare against that (a second live run is not guaranteed bit-identical).
        for key in live_decision.agent_reports:
            assert by_agent[key]["decision"] == by_agent[key]["details"]["signal"]
            assert by_agent[key]["score"] == pytest.approx(by_agent[key]["details"]["confidence"])

    def test_confirmed_trade_has_one_row_per_agent_under_the_trades_signal_id(self, journal, live_decision):
        decision = _confirmed(live_decision)
        _, signal_id = _open_and_close(journal, decision)

        assert signal_id is not None
        rows = {r["agent"]: r for r in _decision_rows(journal, signal_id)}
        assert set(rows) == {"CEO_AGENT"} | set(decision.agent_reports)
        for key, report in decision.agent_reports.items():
            assert rows[key]["decision"] == report["signal"]
            assert rows[key]["weight"] == pytest.approx(decision.weights_used.get(key, 0.0))
            assert rows[key]["symbol"] == SYMBOL


# ══════════════════════════════════════════════════════════════════════════
# 3. Trade level: explicit attribution on the trade, intact after close
# ══════════════════════════════════════════════════════════════════════════

class TestExplicitAttributionOnTrade:

    def test_attribution_has_the_weighted_agents_and_the_ceo(self, journal, live_decision):
        decision = _confirmed(live_decision)
        trade_id, _ = _open_and_close(journal, decision)

        attribution = _explicit_attribution(journal, trade_id)
        assert {a["agent"] for a in attribution} == WEIGHTED_KEYS | {"ceo"}
        by_agent = {a["agent"]: a for a in attribution}
        for key in WEIGHTED_KEYS:
            assert by_agent[key]["vote"] == decision.agent_reports[key]["signal"]
            assert by_agent[key]["weight"] == pytest.approx(decision.weights_used[key])
            assert by_agent[key]["confidence"] == pytest.approx(decision.agent_reports[key]["confidence"])
        assert by_agent["ceo"]["vote"] == "LONG"
        assert by_agent["ceo"]["weight"] == 1.0

    def test_trader_is_a_journaled_row_but_not_an_attribution_entry_by_design(self, journal, live_decision):
        """`trader` is registered with CEOAgent but is not a CEOAgent.WEIGHTS
        key, so its report never enters long_score/short_score (architecture.md
        §30 note 3, §53). Attribution mirrors WEIGHTS (journal/trade_attribution.py
        CEO_WEIGHTED_AGENT_KEYS), so it is journaled in agent_decisions (weight
        0.0) but is not an attribution entry. Locked so a change to either side
        is a deliberate decision, not an accident (§76)."""
        decision = _confirmed(live_decision)
        trade_id, signal_id = _open_and_close(journal, decision)

        assert "trader" in decision.agent_reports and "trader" not in decision.weights_used
        trader_rows = [r for r in _decision_rows(journal, signal_id) if r["agent"] == "trader"]
        assert len(trader_rows) == 1 and trader_rows[0]["weight"] == 0.0
        assert "trader" not in {a["agent"] for a in _explicit_attribution(journal, trade_id)}

    def test_close_does_not_clobber_the_open_time_attribution(self, journal, live_decision):
        decision = _confirmed(live_decision)
        trade_id, _ = _open_and_close(journal, decision)

        row = journal.get_trade_attribution(trade_id)
        assert row["result"] == "WIN" and row["pnl"] == 10.0 and row["source"] is not None
        assert {p["agent"] for p in row["agent_participation"]} == WEIGHTED_KEYS | {"ceo"}


# ══════════════════════════════════════════════════════════════════════════
# 4. Learning-pipeline path (what Phase 4B / 4C actually read)
# ══════════════════════════════════════════════════════════════════════════

class TestLearningDatasetSeesTheVotes:

    def test_ensemble_dataset_row_carries_the_participation(self, journal, live_decision):
        trade_id, _ = _open_and_close(journal, _confirmed(live_decision))

        rows = journal.get_ensemble_learning_dataset()
        assert [r["trade_id"] for r in rows] == [trade_id]
        assert {p["agent"] for p in rows[0]["agent_participation"]} == WEIGHTED_KEYS | {"ceo"}

    def test_learning_dataset_builder_row_carries_the_participation(self, journal, live_decision):
        _open_and_close(journal, _confirmed(live_decision))

        dataset = LearningDatasetBuilder(journal).build()
        assert dataset.row_count == 1
        assert {p["agent"] for p in dataset.rows[0].agent_participation} == WEIGHTED_KEYS | {"ceo"}

    def test_agent_statistics_cover_every_weighted_agent(self, journal, live_decision):
        _open_and_close(journal, _confirmed(live_decision))

        stats = {s.agent: s for s in compute_agent_statistics(LearningDatasetBuilder(journal).build())}
        assert set(stats) == WEIGHTED_KEYS | {"ceo"}
        assert all(s.total_trades == 1 and s.wins == 1 for s in stats.values())

    def test_get_agent_performance_sees_the_voters_whose_vote_matched_the_trade(self, journal, live_decision):
        decision = _confirmed(live_decision)
        _open_and_close(journal, decision)

        perf = {p["agent"]: p for p in journal.get_agent_performance()}
        matched = {k for k in WEIGHTED_KEYS if decision.agent_reports[k]["signal"] == "LONG"} | {"ceo"}
        assert set(perf) == matched
        assert all(p["wins"] == 1 for p in perf.values())


# ══════════════════════════════════════════════════════════════════════════
# 5. No data is missing even without the explicit attribution (backfill note)
# ══════════════════════════════════════════════════════════════════════════

class TestJoinFallbackStillSeesTheVotes:

    def test_trade_without_explicit_attribution_still_has_join_derived_participation(self, journal, live_decision):
        """Step 7C-era shape: signal_id join only. The per-agent rows exist
        either way, which is why §76 needs no backfill for CEO-gated trades
        journaled since Step 7C."""
        trade_id, _ = _open_and_close(journal, _confirmed(live_decision), provider_cls=_NoExplicitAttribution)

        assert _explicit_attribution(journal, trade_id) == []
        participation = journal.get_trade_attribution(trade_id)["agent_participation"]
        assert WEIGHTED_KEYS <= {p["agent"] for p in participation}
