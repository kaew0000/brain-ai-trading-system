"""
tests/test_ceo_multi_symbol_agent_attribution.py — V16 Phase 4C Step 7C:
CEO -> Agent -> Trade Attribution Signal-ID Bridge.

Gap this phase closes (see execution/ceo_gated_signal_provider.py's
_journal_ceo_decision() docstring, "V16 Phase 4C Step 7C" section, for
the full mechanism): journal_v2.get_trade_attribution()'s
agent_participation join is `trades.signal_id == agent_decisions.signal_id`
— before this phase neither side of that join was ever populated for the
CEO-gated multi-symbol path (every save_agent_decision()/save_trade()
call there omitted signal_id, defaulting to None). This phase threads
ONE shared signal_id, created once per CEO decision cycle, through:
CEO_AGENT journal row -> every participating sub-agent's own journal row
-> the outgoing ExecutionSignal -> the trade row execution_orchestrator.py
persists at open time -> journal_v2.get_trade_attribution()'s real join.

TEST DESIGN NOTE — why H5-H9 use a ControlledAdapter, not the real live
MultiSymbolCEODispatcher chain (unlike H1-H4 below, which DO use it):
empirically verified (this phase's own audit) that
tests/test_portfolio_signal_provider.py's _full_market_data() fixture,
run through the real PortfolioSignalProvider -> ConfidenceEngine
pipeline, produces "-> WAIT" (confidence below the confirm threshold)
for trend in {up, down, flat} alike — i.e. map_ceo_decision_to_signal()
always vetoes (underlying_signal stays None) regardless of CEO opinion,
so no live fixture tuning gets a genuinely CONFIRMED trade through the
full pipeline. H5-H9 need a trade to actually reach TradeJournalV2 to
prove anything, so those tests hold the CEO-decision LAYER fixed (a
ControlledAdapter — the exact same duck-typed-fake idiom this project's
own tests/test_ceo_gated_signal_provider.py::FakeAdapter already uses)
while keeping every layer downstream of it 100% real: real
CEOGatedSignalProvider._journal_ceo_decision() (the code under test),
real TradeJournalV2 (tmp_path-backed SQLite, real schema), real
ExecutionOrchestrator.execute(). The CEODecision/AgentReport fed to the
ControlledAdapter are real dataclass instances built through their own
real to_dict() methods, not hand-typed dicts standing in for them.

H1-H4 use the real live dispatcher (real 6-agent layer, real CEOAgent) —
exactly like tests/test_ceo_agent_vote_persistence.py already does —
because those invariants only need a CEO decision to have been produced
(WAIT included; _journal_ceo_decision() journals every cycle regardless
of action), not a confirmed trade.
"""
from __future__ import annotations

import sqlite3

import pytest

from agents.base_agent import AgentReport
from agents.ceo_agent import CEODecision
from agents.ceo_symbol_cache import CEOAgentSymbolCache, MultiSymbolCEODispatcher
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from execution.execution_orchestrator import ExecutionOrchestrator, ExecutionSignal
from execution.execution_state import ExecutionState, ExecutionStatus
from execution.portfolio_signal_provider import PortfolioSignalProvider
from journal.journal_v2 import TradeJournalV2
from portfolio.portfolio_state import PortfolioState
from tests.test_execution_orchestrator import (
    FakeEngine,
    FakePortfolioManager,
    make_allocation,
    make_decision,
)
from tests.test_portfolio_signal_provider import FakeDataProvider, _full_market_data

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _isolated_event_bus():
    """Same isolation convention as tests/test_execution_orchestrator.py
    — ExecutionOrchestrator.execute() publishes through the process-wide
    EventBus singleton by default."""
    from events.event_bus import reset_event_bus
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture
def journal(tmp_path):
    """Real TradeJournalV2 backed by a tmp_path SQLite file — the
    established pattern this project's own tests already use (e.g.
    tests/test_execution_attribution.py::journal), and explicitly NOT a
    process-wide ':memory:' connection, per this phase's own
    test-isolation rule."""
    return TradeJournalV2(db_path=str(tmp_path / "test_journal.db"))


class FakeSignalProviderUnused:
    """CEOGatedSignalProvider's OUTER signal_provider is only ever
    called when gating is disabled — every test here runs enabled=True,
    so this must never actually be invoked. Same convention as
    tests/test_ceo_agent_vote_persistence.py's identical class."""

    def get_signal(self, symbol):
        raise AssertionError("outer signal_provider should not be called when CEO gating is enabled")


class ControlledAdapter:
    """Duck-typed fake matching MultiSymbolCEOAdapter's
    decide_with_signal(symbol) contract — same idiom
    tests/test_ceo_gated_signal_provider.py::FakeAdapter already
    established. See module docstring for why H5-H9 need this instead
    of the live dispatcher."""

    def __init__(self, decision, signal):
        self.decision = decision
        self.signal = signal
        self.calls: list[str] = []

    def decide_with_signal(self, symbol, **kwargs):
        self.calls.append(symbol)
        return self.decision, self.signal


def _make_live_dispatcher(symbol="BTCUSDT", trend="up", price=60000.0):
    """Real chain — no fakes — same helper tests/test_ceo_agent_vote_persistence.py
    and tests/test_recommendation_explanation_persistence.py already use."""
    dp = FakeDataProvider(data_by_symbol={symbol: _full_market_data(symbol=symbol, trend=trend, price=price)})
    provider = PortfolioSignalProvider(data_provider=dp)
    cache = CEOAgentSymbolCache()
    return MultiSymbolCEODispatcher(signal_provider=provider, ceo_agent_cache=cache)


def _confirmed_decision(action="LONG", direction="LONG", confidence=85.0, agents=("smc", "futures", "regime")):
    """A CEODecision with REAL AgentReport.to_dict()-shaped entries
    (built through the real dataclass, not a hand-typed stand-in) —
    same shape agents/ceo_agent.py's decide() itself produces
    (agent_reports = {k: v.to_dict() for k, v in reports.items()})."""
    reports = {
        name: AgentReport(agent=name, signal=direction, confidence=70.0 + i, summary=f"{name} says {direction}").to_dict()
        for i, name in enumerate(agents)
    }
    weights = {name: round(1.0 / len(agents), 4) for name in agents}
    return CEODecision(
        action=action, direction=direction, confidence=confidence,
        agent_reports=reports, weights_used=weights, symbol="BTCUSDT",
    )


def _raw_trade_signal_id(db_path: str, trade_id: int) -> int | None:
    """Direct read of the existing `trades.signal_id` column — no new
    schema, no new journal method, just verifying what Step 7C wrote
    through the journal's own existing save_trade()/schema, exactly
    like journal_v2.get_agent_performance()'s own query already joins
    on this same real column."""
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT signal_id FROM trades WHERE id=?", (trade_id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


# ══════════════════════════════════════════════════════════════════════════
# H1 — one signal_id per CEO decision cycle
# ══════════════════════════════════════════════════════════════════════════

class TestH1OneSignalIdPerCycle:

    def test_wait_cycle_still_creates_exactly_one_shared_signal_id(self, journal):
        """H1 is about the DECISION CYCLE, not about whether a trade
        results — a WAIT cycle (verified: this fixture always produces
        WAIT, see module docstring) still creates exactly one signals
        row, shared by every journaled row from this cycle."""
        dispatcher = _make_live_dispatcher(trend="up")
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True)

        result = gated.get_signal("BTCUSDT")

        assert result is None  # WAIT -> no trade to confirm
        signals = journal.get_signals(limit=10, symbol="BTCUSDT")
        assert len(signals) == 1

        rows = journal.get_agent_decisions(limit=50)
        assert len(rows) >= 2  # CEO_AGENT + at least one real sub-agent
        assert len({r["signal_id"] for r in rows}) == 1  # every row this cycle shares ONE id


# ══════════════════════════════════════════════════════════════════════════
# H2 — CEO_AGENT row receives the shared signal_id
# ══════════════════════════════════════════════════════════════════════════

class TestH2CeoRowGetsSharedId:

    def test_ceo_agent_row_carries_the_cycles_signal_id(self, journal):
        dispatcher = _make_live_dispatcher(trend="up")
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")

        shared_id = journal.get_signals(limit=10, symbol="BTCUSDT")[0]["id"]
        ceo_rows = journal.get_agent_decisions(agent="CEO_AGENT", limit=10)
        assert len(ceo_rows) == 1
        assert ceo_rows[0]["signal_id"] == shared_id


# ══════════════════════════════════════════════════════════════════════════
# H3 — every participating sub-agent row shares the SAME signal_id
# ══════════════════════════════════════════════════════════════════════════

class TestH3AgentRowsShareSameId:

    def test_every_real_sub_agent_row_has_the_ceo_cycles_signal_id(self, journal):
        dispatcher = _make_live_dispatcher(trend="up")
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")

        shared_id = journal.get_signals(limit=10, symbol="BTCUSDT")[0]["id"]
        ceo_row = journal.get_agent_decisions(agent="CEO_AGENT", limit=10)[0]
        expected_agents = set(ceo_row["details"]["agent_reports"].keys())
        assert len(expected_agents) > 0  # real agent layer genuinely voted

        all_rows = journal.get_agent_decisions(limit=50)
        sub_agent_rows = [r for r in all_rows if r["agent"] != "CEO_AGENT"]

        assert {r["agent"] for r in sub_agent_rows} == expected_agents
        assert all(r["signal_id"] == shared_id for r in sub_agent_rows)
        assert len(sub_agent_rows) == len(expected_agents)  # no duplicates, no independently-minted ids


# ══════════════════════════════════════════════════════════════════════════
# H4 — per-agent attribution stays independently inspectable (not collapsed)
# ══════════════════════════════════════════════════════════════════════════

class TestH4PerAgentAttributionPreserved:

    def test_each_agent_is_its_own_row_not_one_merged_blob(self, journal):
        dispatcher = _make_live_dispatcher(trend="up")
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")

        all_rows = journal.get_agent_decisions(limit=50)
        sub_agent_rows = [r for r in all_rows if r["agent"] != "CEO_AGENT"]
        assert len(sub_agent_rows) >= 1

        # distinct primary keys — genuinely separate rows, not one row
        # with all agents folded into a single details blob
        assert len({r["id"] for r in sub_agent_rows}) == len(sub_agent_rows)
        for r in sub_agent_rows:
            assert isinstance(r["decision"], str) and r["decision"] != ""
            assert isinstance(r["score"], (int, float))
            assert isinstance(r["weight"], (int, float))
            assert isinstance(r["details"], dict)
            # each row's own details is that ONE agent's report, not the
            # whole agent_reports dict (which is only on the CEO_AGENT row)
            assert "agent_reports" not in r["details"]


# ══════════════════════════════════════════════════════════════════════════
# H5 — ExecutionSignal carries the CEO cycle's signal_id
# ══════════════════════════════════════════════════════════════════════════

class TestH5ExecutionSignalCarriesId:

    def test_confirmed_signal_carries_the_shared_signal_id(self, journal):
        decision = _confirmed_decision()
        signal = ExecutionSignal(direction=1, entry_price=60_000.0, stop_loss=59_000.0, take_profit=62_000.0)
        adapter = ControlledAdapter(decision, signal)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        result = gated.get_signal("BTCUSDT")

        assert result is not None
        assert result.signal_id is not None
        shared_id = journal.get_signals(limit=10, symbol="BTCUSDT")[0]["id"]
        assert result.signal_id == shared_id
        # H5 must not mutate the caller's underlying signal in place —
        # ExecutionSignal is frozen; a NEW instance carries the id.
        assert signal.signal_id is None

    def test_vetoed_signal_carries_no_id_there_is_nothing_to_attach_it_to(self, journal):
        """CEO disagrees with the priced direction -> None. There's no
        ExecutionSignal to carry an id, even though a signal_id WAS
        created and journaled (H1) for audit purposes."""
        decision = _confirmed_decision(action="SHORT", direction="SHORT")
        signal = ExecutionSignal(direction=1, entry_price=60_000.0, stop_loss=59_000.0, take_profit=62_000.0)
        adapter = ControlledAdapter(decision, signal)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        result = gated.get_signal("BTCUSDT")

        assert result is None
        assert len(journal.get_signals(limit=10, symbol="BTCUSDT")) == 1  # still journaled (H1)


# ══════════════════════════════════════════════════════════════════════════
# H6 — trade-open persistence reuses the incoming signal_id (both halves)
# ══════════════════════════════════════════════════════════════════════════

class TestH6TradeReusesId:

    def test_signal_with_id_is_reused_not_duplicated(self, journal):
        """An incoming signal_id on the ExecutionSignal means ZERO new
        signal rows minted at trade-open time — the one
        _journal_ceo_decision() already created is reused end to end."""
        decision = _confirmed_decision()
        signal = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)
        adapter = ControlledAdapter(decision, signal)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        orch = ExecutionOrchestrator(
            execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
            signal_provider=gated, state=ExecutionState(), journal=journal,
        )
        pstate = PortfolioState()
        batch = orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)

        assert batch.results[0].status == ExecutionStatus.COMPLETED
        assert len(journal.get_signals(limit=10)) == 1  # reused, not duplicated

    def test_signal_without_id_still_mints_a_fresh_one_unchanged(self, journal):
        """Backward-compat half: every pre-Step-7C caller (plain
        portfolio_signal_provider.py path, strategy_registry.py) never
        set signal_id — behavior there is byte-identical to before."""
        orch = ExecutionOrchestrator(
            execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
            signal_provider=lambda s: ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0),
            state=ExecutionState(), journal=journal,
        )
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)

        trade_id = pstate.get_position("BTCUSDT").trade_id
        assert trade_id is not None
        assert journal.get_trades(limit=10)[0]["signal_id"] is not None  # a fresh one WAS minted
        assert len(journal.get_signals(limit=10)) == 1


# ══════════════════════════════════════════════════════════════════════════
# H7 — trade.signal_id == agent_decision.signal_id (the raw join)
# ══════════════════════════════════════════════════════════════════════════

class TestH7AttributionJoinWorks:

    def test_trade_signal_id_matches_agent_decision_signal_id(self, journal):
        decision = _confirmed_decision(agents=("smc", "futures", "regime"))
        signal = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)
        adapter = ControlledAdapter(decision, signal)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        orch = ExecutionOrchestrator(
            execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
            signal_provider=gated, state=ExecutionState(), journal=journal,
        )
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)
        trade_id = pstate.get_position("BTCUSDT").trade_id

        trade_signal_id = _raw_trade_signal_id(journal.db_path, trade_id)
        assert trade_signal_id is not None

        agent_rows = journal.get_agent_decisions(limit=50)
        matching = [r for r in agent_rows if r["signal_id"] == trade_signal_id]
        # CEO_AGENT + the 3 sub-agents from _confirmed_decision(), all
        # sharing trade.signal_id
        assert {r["agent"] for r in matching} == {"CEO_AGENT", "smc", "futures", "regime"}


# ══════════════════════════════════════════════════════════════════════════
# H8 — the real get_trade_attribution() reader actually sees the agents
# ══════════════════════════════════════════════════════════════════════════

class TestH8GetTradeAttributionSeesAgents:

    def test_get_trade_attribution_populates_agent_participation(self, journal):
        """Not raw-row inspection — the real, documented reader
        (journal_v2.get_trade_attribution(), already backing
        /api/trades/{id}/attribution or equivalent) must itself surface
        this trade's attribution.

        V16 W14-2A: execution_orchestrator.py's _record_trade_opened()
        now threads ExecutionSignal.agent_attribution (built by
        ceo_gated_signal_provider.py via
        agent_attribution_from_ceo_decision()) into
        TradeLifecycle.open_confirmed() -> record_trade_outcome() ->
        save_execution_attribution(), so this trade now carries an
        EXPLICIT agent_attribution. get_trade_attribution()'s own
        pre-existing, already-documented precedence rule ("if the trade
        carries an explicit agent_attribution... that is returned as-is
        instead of the join — the explicit value is assumed more
        complete") means this test now exercises that explicit-value
        branch rather than the agent_decisions join it exercised before
        this phase had a live caller for it. journal/trade_attribution.py's
        canonical agent key for the CEO's own entry is "ceo" (see that
        module's own docstring — it is not itself a CEOAgent.WEIGHTS key,
        so it is not named "CEO_AGENT" as agent_decisions rows are), and
        its contribution values come from CEODecision.score_breakdown —
        which this test's own _confirmed_decision() helper leaves empty
        — not from a confidence*weight reconstruction. The
        agent_decisions join itself (rows keyed by trade.signal_id) is
        unchanged and still covered directly by TestH7AttributionJoinWorks
        above and test_pre_step7c_trade_still_returns_empty_participation_not_fabricated
        below (both exercise cases with no explicit agent_attribution on
        the trade)."""
        decision = _confirmed_decision(agents=("smc", "futures"))
        signal = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)
        adapter = ControlledAdapter(decision, signal)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        orch = ExecutionOrchestrator(
            execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
            signal_provider=gated, state=ExecutionState(), journal=journal,
        )
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)
        trade_id = pstate.get_position("BTCUSDT").trade_id

        attribution = journal.get_trade_attribution(trade_id)

        assert attribution is not None
        assert attribution["trade_id"] == trade_id
        participation = attribution["agent_participation"]
        # 2 sub-agents (smc, futures) + the CEO's own aggregate entry —
        # journal/trade_attribution.py's CEO_WEIGHTED_AGENT_KEYS-driven
        # shape, not the agent_decisions join.
        assert len(participation) == 3
        agents_seen = {p["agent"] for p in participation}
        assert agents_seen == {"ceo", "smc", "futures"}
        for p in participation:
            assert set(p.keys()) == {"agent", "vote", "weight", "confidence", "contribution"}
            assert p["vote"] == "LONG"
        ceo_entry = next(p for p in participation if p["agent"] == "ceo")
        assert ceo_entry["weight"] == 1.0
        assert ceo_entry["confidence"] == decision.confidence
        assert ceo_entry["contribution"] == decision.confidence
        for p in participation:
            if p["agent"] != "ceo":
                # _confirmed_decision() never populates score_breakdown,
                # so contribution is honestly None here rather than a
                # fabricated confidence*weight value — matches
                # agent_attribution_from_ceo_decision()'s own documented
                # "never fabricate" contract.
                assert p["contribution"] is None

    def test_pre_step7c_trade_still_returns_empty_participation_not_fabricated(self, journal):
        """Backward compatibility: a trade with no signal_id (the
        pre-Step-7C / plain-path shape) still gets an honestly EMPTY
        agent_participation — get_trade_attribution() must never
        fabricate entries. Matches this method's own pre-existing
        docstring guarantee."""
        orch = ExecutionOrchestrator(
            execution_engine=FakeEngine(), portfolio_manager=FakePortfolioManager(),
            signal_provider=lambda s: ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0),
            state=ExecutionState(), journal=journal,
        )
        pstate = PortfolioState()
        orch.execute(make_decision(selected=[make_allocation()]), pstate, 1_000.0)
        trade_id = pstate.get_position("BTCUSDT").trade_id

        attribution = journal.get_trade_attribution(trade_id)
        assert attribution["agent_participation"] == []


# ══════════════════════════════════════════════════════════════════════════
# H9 — multi-symbol isolation
# ══════════════════════════════════════════════════════════════════════════

class TestH9MultiSymbolIsolation:

    def test_two_symbols_in_the_same_journal_never_cross_attribute(self, journal):
        decision_btc = _confirmed_decision(action="LONG", direction="LONG", agents=("smc", "futures"))
        signal_btc = ExecutionSignal(direction=1, entry_price=60_000.0, stop_loss=59_000.0, take_profit=62_000.0)
        gated_btc = CEOGatedSignalProvider(
            FakeSignalProviderUnused(), ControlledAdapter(decision_btc, signal_btc), journal=journal, enabled=True,
        )

        decision_eth = _confirmed_decision(action="SHORT", direction="SHORT", agents=("regime", "risk"))
        signal_eth = ExecutionSignal(direction=-1, entry_price=3_000.0, stop_loss=3_100.0, take_profit=2_800.0)
        gated_eth = CEOGatedSignalProvider(
            FakeSignalProviderUnused(), ControlledAdapter(decision_eth, signal_eth), journal=journal, enabled=True,
        )

        result_btc = gated_btc.get_signal("BTCUSDT")
        result_eth = gated_eth.get_signal("ETHUSDT")

        assert result_btc is not None and result_eth is not None
        assert result_btc.signal_id != result_eth.signal_id  # A != B

        all_rows = journal.get_agent_decisions(limit=50)
        btc_agents = {r["agent"] for r in all_rows if r["signal_id"] == result_btc.signal_id}
        eth_agents = {r["agent"] for r in all_rows if r["signal_id"] == result_eth.signal_id}

        assert btc_agents == {"CEO_AGENT", "smc", "futures"}
        assert eth_agents == {"CEO_AGENT", "regime", "risk"}
        # no sub-agent row leaked across the two decision cycles
        assert (btc_agents - {"CEO_AGENT"}).isdisjoint(eth_agents - {"CEO_AGENT"})


# ══════════════════════════════════════════════════════════════════════════
# Backward compatibility & failure isolation
# ══════════════════════════════════════════════════════════════════════════

class TestBackwardCompatibility:

    def test_execution_signal_positional_construction_unaffected(self):
        """Every pre-Step-7C ExecutionSignal(...) call site (and every
        existing test's literal) constructs with exactly 4 positional/
        keyword args — signal_id's default must not require a 5th."""
        sig = ExecutionSignal(1, 100.0, 90.0, 110.0)
        assert sig.signal_id is None

    def test_no_journal_configured_is_still_a_complete_noop(self):
        dispatcher = _make_live_dispatcher(trend="up")
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=None, enabled=True)
        assert gated.get_signal("BTCUSDT") is None  # must not raise with journal=None

    def test_empty_agents_ceoagent_still_journals_cleanly_with_shared_id(self, journal):
        """Step 7's own pre-existing edge case (CEOAgent(agents={})) —
        Step 7C must not break it: CEO_AGENT row still gets a signal_id,
        the (empty) agent_reports loop simply iterates zero times."""
        from agents.ceo_agent import CEOAgent

        ceo = CEOAgent(agents={})

        class _DirectAdapter:
            def decide_with_signal(self, symbol, **kwargs):
                return ceo.decide({"symbol": symbol, "regime": "TRENDING"}), None

        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), _DirectAdapter(), journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        rows = journal.get_agent_decisions(limit=10)
        assert len(rows) == 1  # CEO_AGENT only, zero sub-agents
        assert rows[0]["agent"] == "CEO_AGENT"
        assert rows[0]["signal_id"] is not None


class TestFailureIsolation:

    class _NoSaveSignalJournal:
        """A journal double that supports save_agent_decision but NOT
        save_signal — proves _journal_ceo_decision() degrades to
        signal_id=None (graceful, non-fatal) rather than raising, same
        as this project's other best-effort journal writes."""

        def __init__(self):
            self.saved = []

        def save_agent_decision(self, **kwargs):
            self.saved.append(kwargs)

    def test_save_signal_failure_degrades_to_none_not_a_crash(self):
        dispatcher = _make_live_dispatcher(trend="up")
        journal = self._NoSaveSignalJournal()
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), dispatcher, journal=journal, enabled=True)

        result = gated.get_signal("BTCUSDT")  # must not raise

        assert result is None  # WAIT fixture
        assert len(journal.saved) >= 1
        assert all(row["signal_id"] is None for row in journal.saved)

    def test_one_agents_journal_failure_does_not_stop_the_others(self, journal):
        """A per-agent save_agent_decision() failure for ONE agent must
        not prevent the remaining agents (or the CEO_AGENT row) from
        being journaled — same non-fatal, isolated-per-write convention
        as every other journal call in this method."""
        decision = _confirmed_decision(agents=("smc", "futures", "regime"))

        real_save = journal.save_agent_decision
        calls = {"n": 0}

        def flaky_save(**kwargs):
            calls["n"] += 1
            if kwargs.get("agent") == "futures":
                raise RuntimeError("simulated DB failure for one agent")
            return real_save(**kwargs)

        journal.save_agent_decision = flaky_save  # type: ignore[method-assign]

        adapter = ControlledAdapter(decision, None)
        gated = CEOGatedSignalProvider(FakeSignalProviderUnused(), adapter, journal=journal, enabled=True)

        gated.get_signal("BTCUSDT")  # must not raise

        rows = journal.get_agent_decisions(limit=10)
        agents_saved = {r["agent"] for r in rows}
        # CEO_AGENT + smc + regime persisted; "futures" was the one
        # simulated failure and is legitimately absent
        assert agents_saved == {"CEO_AGENT", "smc", "regime"}
