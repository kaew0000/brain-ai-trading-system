"""
tests/test_w14_2a_attribution_wiring.py — V16 W14-2A: CEO-to-Agent
Attribution Pipeline Wiring

Covers the two live call sites this phase adds for
journal/trade_attribution.py's agent_attribution_from_ceo_decision()
(previously implemented and tested, but with no production caller):

  Path A — main.py's single-symbol run_trading_cycle() (the default,
           settings.CEO_MULTI_SYMBOL_ENABLED=False live loop): attribution
           is built from the cycle's own ceo_decision and persisted via
           journal_v2.save_execution_attribution() right after the trade
           row is saved.

  Path B — execution/ceo_gated_signal_provider.py's
           CEOGatedSignalProvider._get_signal_ceo_enabled() (the
           CEO_MULTI_SYMBOL_ENABLED=True path): attribution is threaded
           onto the outgoing ExecutionSignal.agent_attribution, consumed
           by execution/execution_orchestrator.py's _record_trade_opened()
           -> TradeLifecycle.open_confirmed() -> record_trade_outcome()
           (all three pre-existing, unmodified in this phase except for
           execution_orchestrator.py threading the one new field through).

This file exercises the REAL run_trading_cycle() with a fully mocked
`sys` dict (same idiom as tests/test_mission_pipeline_integration.py),
not just import-without-crashing coverage.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────
# Shared fixtures (lifecycle must be RUNNING for run_trading_cycle to do
# anything at all — see main.py's W14-0 early-return near the top of the
# function).
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


@pytest.fixture
def running_bot():
    from commander.control_state import get_control_state, reset_control_state
    reset_control_state()
    get_control_state().start()
    yield
    reset_control_state()


@pytest.fixture
def stopped_bot():
    """Lifecycle stays at its default (STOPPED) — used for the
    lifecycle-safety test (Part F)."""
    from commander.control_state import reset_control_state
    reset_control_state()
    yield
    reset_control_state()


def _make_ceo_decision(action="LONG", confidence=82.0, agent_reports=None, weights_used=None):
    """A CEODecision-shaped MagicMock — mirrors
    tests/test_mission_pipeline_integration.py's _make_decision() idiom,
    but for agents.get('ceo').decide()'s return value specifically."""
    agent_reports = agent_reports if agent_reports is not None else {
        "smc":     {"signal": "LONG", "confidence": 70.0},
        "futures": {"signal": "LONG", "confidence": 65.0},
    }
    weights_used = weights_used if weights_used is not None else {"smc": 0.3, "futures": 0.2}
    d = MagicMock()
    d.action = action
    d.confidence = confidence
    d.agent_reports = agent_reports
    d.to_dict.return_value = {
        "action": action,
        "confidence": confidence,
        "agent_reports": agent_reports,
        "weights_used": weights_used,
        "score_breakdown": {},
    }
    return d


def _make_decision(action="LONG", confidence=78.0):
    d = MagicMock()
    d.action = action
    d.direction = action
    d.entry_price = 67000.0
    d.stop_loss = 65800.0
    d.take_profit = 69400.0
    d.confidence = confidence
    d.regime = "TREND"
    d.oi_delta = 0.012
    d.funding_rate = 0.0001
    d.mtf_aligned = True
    d.raw_score = 7
    d.breakdown = {}
    d.block_reasons = []
    d.to_dict.return_value = {
        "action": action, "direction": action, "confidence": confidence,
        "entry_price": 67000.0, "stop_loss": 65800.0, "take_profit": 69400.0,
        "regime": "TREND", "raw_score": 7, "score": 7,
    }
    return d


def _make_sys_dict(ceo_decision=None, exec_success=True, jrn=None):
    """Same shape as test_mission_pipeline_integration.py's
    _make_sys_dict(), plus an optional agents.get('ceo') mock so
    run_trading_cycle()'s 10a CEO branch actually runs."""
    from missions.mission_tracker import get_mission_tracker

    dp = MagicMock()
    dp.get_position_info.return_value = None
    dp.get_all_market_data.return_value = {
        "ohlcv": {"h1": MagicMock(), "h4": MagicMock(), "m15": MagicMock()},
        "funding_rate": 0.0001, "open_interest": 15000.0, "oi_delta": 0.012,
    }
    dp.get_account_balance.return_value = 10_000.0
    dp.get_mark_price.return_value = 67000.0
    dp._sync_time_offset = MagicMock()

    regime_result = MagicMock()
    regime_result.regime = "TREND"
    regime_result.confidence = 0.7
    regime_result.to_dict.return_value = {"regime": "TREND", "confidence": 0.7}
    reg = MagicMock()
    reg.classify.return_value = regime_result

    from features.smc_engine import SMCSignals
    smc = MagicMock()
    smc.analyze_mtf.return_value = {"m15": SMCSignals(), "h1": SMCSignals(), "h4": SMCSignals()}

    from features.volume_engine import VolumeSignals
    vol = MagicMock()
    vol.analyze.return_value = VolumeSignals()

    ctxb = MagicMock()
    ctxb.build.return_value = {
        "mtf_direction": "LONG", "mtf_aligned": True,
        "mark_price": 67000.0, "regime": "TREND", "futures": {},
    }

    decision = _make_decision(action="LONG")
    ce = MagicMock()
    ce.score.return_value = decision

    expl = MagicMock()
    explanation_result = MagicMock()
    explanation_result.to_dict.return_value = {"summary": "test"}
    expl.explain.return_value = explanation_result

    if jrn is None:
        jrn = MagicMock()
        jrn.get_open_trades.return_value = []
        jrn.save_signal = MagicMock(return_value=None)
        jrn.save_market_regime = MagicMock()
        jrn.save_funding = MagicMock()
        jrn.save_oi = MagicMock()
        jrn.save_trade.return_value = 1
        jrn.save_execution_attribution = MagicMock(return_value=True)
        jrn.update_trade_result = MagicMock()

    rsk = MagicMock()
    rsk.can_trade.return_value = (True, "")
    rsk.get_risk_pct.return_value = 0.01
    rsk.get_leverage.return_value = 5

    tm = MagicMock()
    tm.execute_trade.return_value = (
        {"success": True, "quantity": 0.1, "entry_order": {"orderId": "123"}}
        if exec_success else
        {"success": False, "error": "insufficient margin"}
    )

    agent_layer = {}
    if ceo_decision is not None:
        ceo = MagicMock()
        ceo.decide.return_value = ceo_decision
        ceo.WEIGHTS = {"smc": 0.3, "futures": 0.2}
        agent_layer = {"ceo": ceo}

    from events.event_bus import get_event_bus
    bus = get_event_bus()

    return {
        "data_provider":     dp,
        "smc_engine":        smc,
        "volume_engine":     vol,
        "regime_engine":     reg,
        "context_builder":   ctxb,
        "confidence_engine": ce,
        "causal_explainer":  expl,
        "journal_v2":        jrn,
        "risk_engine":       rsk,
        "trade_manager":     tm,
        "event_bus":         bus,
        "agent_layer":       agent_layer,
        "mission_tracker":   get_mission_tracker(),
        "current_mission_id": None,
    }


# ─────────────────────────────────────────────────────────────────────────
# Part A/B/C — live call path, correct identifiers, persistence
# ─────────────────────────────────────────────────────────────────────────

class TestPathALiveCallSite:
    """main.py's single-symbol run_trading_cycle() — the default
    (CEO_MULTI_SYMBOL_ENABLED=False) live loop."""

    def test_attribution_persisted_against_the_trade_that_actually_opened(self, running_bot):
        from main import run_trading_cycle
        ceo_decision = _make_ceo_decision()
        sys_dict = _make_sys_dict(ceo_decision=ceo_decision)

        run_trading_cycle(sys_dict)

        jrn = sys_dict["journal_v2"]
        assert jrn.save_execution_attribution.call_count == 1
        call = jrn.save_execution_attribution.call_args
        # Correct identifier: trade_id is the SAME id save_trade() just
        # returned (1, per this fixture's jrn.save_trade.return_value),
        # not a fabricated or unrelated one.
        assert call.args[0] == 1
        attribution = call.kwargs["agent_attribution"]
        assert {"agent": "ceo", "vote": "LONG"}.items() <= next(
            a for a in attribution if a["agent"] == "ceo"
        ).items()
        assert any(a["agent"] == "smc" for a in attribution)
        assert any(a["agent"] == "futures" for a in attribution)

    def test_no_ceo_decision_this_cycle_persists_no_attribution(self, running_bot):
        """agent_layer={} (no ceo configured) -> ceo_decision stays None
        (main.py 10a) -> nothing to build attribution from. Must not
        fabricate a placeholder."""
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(ceo_decision=None)

        run_trading_cycle(sys_dict)

        sys_dict["journal_v2"].save_execution_attribution.assert_not_called()

    def test_missing_agent_votes_are_omitted_not_fabricated(self, running_bot):
        """Part E — Data integrity: only smc reported this cycle; futures/
        regime/risk/journal/confidence_engine did not. The attribution
        list must contain only smc + ceo, never a fabricated zeroed entry
        for the agents that didn't report."""
        from main import run_trading_cycle
        ceo_decision = _make_ceo_decision(
            agent_reports={"smc": {"signal": "LONG", "confidence": 70.0}},
            weights_used={"smc": 0.3},
        )
        sys_dict = _make_sys_dict(ceo_decision=ceo_decision)

        run_trading_cycle(sys_dict)

        attribution = sys_dict["journal_v2"].save_execution_attribution.call_args.kwargs["agent_attribution"]
        agents_present = {a["agent"] for a in attribution}
        assert agents_present == {"smc", "ceo"}

    def test_attribution_persist_failure_never_breaks_the_trade(self, running_bot):
        """Attribution is diagnostic/audit data — a persistence failure
        here must be logged and swallowed, never propagate and never
        affect the fact that the trade itself already executed."""
        from main import run_trading_cycle
        ceo_decision = _make_ceo_decision()
        jrn = MagicMock()
        jrn.get_open_trades.return_value = []
        jrn.save_signal = MagicMock(return_value=None)
        jrn.save_market_regime = MagicMock()
        jrn.save_funding = MagicMock()
        jrn.save_oi = MagicMock()
        jrn.save_trade.return_value = 1
        jrn.save_execution_attribution = MagicMock(side_effect=RuntimeError("simulated DB failure"))
        jrn.update_trade_result = MagicMock()
        sys_dict = _make_sys_dict(ceo_decision=ceo_decision, jrn=jrn)

        run_trading_cycle(sys_dict)  # must not raise

        jrn.save_execution_attribution.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────
# Part D — duplicate/retry
# ─────────────────────────────────────────────────────────────────────────

class TestIdempotency:

    def test_calling_the_builder_twice_produces_identical_content(self, running_bot):
        """agent_attribution_from_ceo_decision() is a pure function of
        ceo_decision — re-running the same cycle's inputs (e.g. a retry)
        yields byte-identical attribution content, not a second,
        divergent copy. save_execution_attribution() itself (existing,
        unmodified) merges into trades.extra_data by trade_id rather
        than appending, so a duplicate call is a no-op overwrite."""
        from journal.trade_attribution import agent_attribution_from_ceo_decision
        ceo_decision = _make_ceo_decision()
        first = agent_attribution_from_ceo_decision(ceo_decision.to_dict())
        second = agent_attribution_from_ceo_decision(ceo_decision.to_dict())
        assert first == second

    def test_ceo_gated_provider_returns_same_attribution_across_calls(self, running_bot):
        """Path B: calling get_signal() twice for the same decision
        content threads the same attribution both times."""
        from agents.ceo_agent import CEODecision
        from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
        from execution.execution_orchestrator import ExecutionSignal

        signal = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)
        decision = CEODecision(
            action="LONG", direction="LONG", confidence=85.0,
            agent_reports={"smc": {"signal": "LONG", "confidence": 70.0}},
            weights_used={"smc": 0.3},
        )

        class FakeAdapter:
            def decide_with_signal(self, symbol):
                return decision, signal

        class FakeSignalProvider:
            def get_signal(self, symbol):
                return None

        gated = CEOGatedSignalProvider(FakeSignalProvider(), FakeAdapter(), enabled=True)
        first = gated.get_signal("BTCUSDT")
        second = gated.get_signal("BTCUSDT")
        assert first.agent_attribution == second.agent_attribution


# ─────────────────────────────────────────────────────────────────────────
# Part F — lifecycle safety (W14-0 must keep working)
# ─────────────────────────────────────────────────────────────────────────

class TestLifecycleSafety:

    def test_stopped_lifecycle_never_builds_or_persists_attribution(self, stopped_bot):
        """W14-0: lifecycle_state defaults to STOPPED. run_trading_cycle()
        must early-return before EVER reaching the CEO decision step (10a)
        or the attribution call this phase adds — attribution must never
        be able to make a STOPPED bot look like it traded."""
        from main import run_trading_cycle
        ceo_decision = _make_ceo_decision()
        sys_dict = _make_sys_dict(ceo_decision=ceo_decision)

        run_trading_cycle(sys_dict)

        sys_dict["journal_v2"].save_trade.assert_not_called()
        sys_dict["journal_v2"].save_execution_attribution.assert_not_called()
        sys_dict["trade_manager"].execute_trade.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# Part G — paper/live separation for this call site
# ─────────────────────────────────────────────────────────────────────────

class TestPaperLiveSeparation:

    def test_paper_mode_forced_never_persists_attribution(self, running_bot):
        """Commander's paper-mode safety override (pre-existing, W14-0
        adjacent) skips execution entirely — this phase's attribution
        call sits AFTER that skip's `return`, so a forced-paper cycle
        must never reach it either. No new routing is introduced by this
        phase; this only confirms the existing early-return already
        covers the new call site."""
        from commander.control_state import get_control_state
        get_control_state().set_paper_mode_forced(True)

        from main import run_trading_cycle
        ceo_decision = _make_ceo_decision()
        sys_dict = _make_sys_dict(ceo_decision=ceo_decision)

        run_trading_cycle(sys_dict)

        sys_dict["journal_v2"].save_execution_attribution.assert_not_called()
        sys_dict["trade_manager"].execute_trade.assert_not_called()
