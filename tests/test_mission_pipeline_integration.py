"""
tests/test_mission_pipeline_integration.py
=============================================
v14 Phase 2.5 — Mission Pipeline integration tests.

main.py has no direct unit test coverage anywhere in this codebase (it's
pure orchestration). This file specifically exercises the REAL
run_trading_cycle() / monitor_open_trades() functions with a fully mocked
`sys` dict, to give genuine regression coverage of the mission lifecycle
wiring added in this phase — not just "the file imports without crashing".

Three lifecycle paths are covered end-to-end:
  1. Full success:  SIGNAL_FOUND → VALIDATION → RISK_CHECK → EXECUTION →
                     MONITORING (next cycle) → CLOSED (on exchange close)
  2. Risk-blocked:   SIGNAL_FOUND → VALIDATION → CLOSED (abort)
  3. Execution-failed: SIGNAL_FOUND → VALIDATION → RISK_CHECK → CLOSED (abort)

Also verifies: mission tracker failures NEVER raise out of run_trading_cycle
or monitor_open_trades (defensive try/except contract).
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_mission_tracker():
    from missions.mission_tracker import reset_mission_tracker
    reset_mission_tracker()
    yield
    reset_mission_tracker()


@pytest.fixture(autouse=True)
def reset_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


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


def _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True,
                    has_open_position=False):
    """Build a fully-mocked `sys` dict matching build_system()'s shape."""
    from missions.mission_tracker import get_mission_tracker

    dp = MagicMock()
    dp.get_position_info.return_value = (
        {"side": "LONG", "positionAmt": "0.1", "entryPrice": 67000.0,
         "unrealizedProfit": 5.0} if has_open_position else None
    )
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
        "mtf_direction": decision_action if decision_action in ("LONG", "SHORT") else "",
        "mtf_aligned": True,
        "mark_price": 67000.0,
        "regime": "TREND",
        "futures": {},
    }

    decision = _make_decision(action=decision_action)
    ce = MagicMock()
    ce.score.return_value = decision

    expl = MagicMock()
    explanation_result = MagicMock()
    explanation_result.to_dict.return_value = {"summary": "test"}
    expl.explain.return_value = explanation_result

    jrn = MagicMock()
    jrn.get_open_trades.return_value = []
    jrn.save_signal = MagicMock()
    jrn.save_market_regime = MagicMock()
    jrn.save_funding = MagicMock()
    jrn.save_oi = MagicMock()
    jrn.save_trade.return_value = 1
    jrn.update_trade_result = MagicMock()

    rsk = MagicMock()
    rsk.can_trade.return_value = (risk_ok, "" if risk_ok else "Daily loss limit exceeded")
    rsk.get_risk_pct.return_value = 0.01
    # P1-B1: stub the new get_leverage(atr_pct=...) call — see test_commander.py
    # for why an un-stubbed MagicMock return value here breaks main.py.
    rsk.get_leverage.return_value = 5

    tm = MagicMock()
    tm.execute_trade.return_value = (
        {"success": True, "quantity": 0.1, "entry_order": {"orderId": "123"}}
        if exec_success else
        {"success": False, "error": "insufficient margin"}
    )

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
        "agent_layer":       {},   # empty — agent layer not under test here
        "mission_tracker":   get_mission_tracker(),
        "current_mission_id": None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Path 1: Full success lifecycle
# ─────────────────────────────────────────────────────────────────────────────
class TestFullSuccessPath:

    def test_mission_created_on_long_signal(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        tracker = sys_dict["mission_tracker"]
        active = tracker.get_active()
        assert len(active) == 1

    def test_mission_reaches_execution_stage(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        tracker = sys_dict["mission_tracker"]
        mission_id = sys_dict["current_mission_id"]
        assert mission_id is not None
        mission = tracker.get(mission_id)
        assert mission.stage == "EXECUTION"

    def test_mission_history_has_all_intermediate_stages(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        tracker = sys_dict["mission_tracker"]
        mission = tracker.get(sys_dict["current_mission_id"])
        stages_seen = [h["stage"] for h in mission.history]
        assert stages_seen == ["SIGNAL_FOUND", "VALIDATION", "RISK_CHECK", "EXECUTION"]

    def test_mission_advances_to_monitoring_on_next_cycle(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)   # cycle 1: creates + executes mission
        mission_id = sys_dict["current_mission_id"]

        # Cycle 2: position now shows as open on the exchange
        sys_dict["data_provider"].get_position_info.return_value = {
            "side": "LONG", "positionAmt": "0.1",
            "entryPrice": 67000.0, "unrealizedProfit": 8.0,
        }
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.get(mission_id)
        assert mission.stage == "MONITORING"

    def test_mission_closes_when_position_resolves(self):
        from main import run_trading_cycle, monitor_open_trades
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        mission_id = sys_dict["current_mission_id"]

        # Simulate the journal showing one open trade that has now closed
        sys_dict["journal_v2"].get_open_trades.return_value = [{
            "id": 1, "entry_price": 67000.0, "stop_loss": 65800.0,
            "take_profit": 69400.0, "direction": "LONG", "quantity": 0.1,
        }]
        sys_dict["data_provider"].get_position_info.return_value = None  # closed on exchange
        sys_dict["data_provider"].get_mark_price.return_value = 69500.0  # hit TP

        monitor_open_trades(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.get(mission_id)
        assert mission.stage == "CLOSED"
        assert sys_dict["current_mission_id"] is None

    def test_mission_meta_has_pnl_after_close(self):
        from main import run_trading_cycle, monitor_open_trades
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        mission_id = sys_dict["current_mission_id"]

        sys_dict["journal_v2"].get_open_trades.return_value = [{
            "id": 1, "entry_price": 67000.0, "stop_loss": 65800.0,
            "take_profit": 69400.0, "direction": "LONG", "quantity": 0.1,
        }]
        sys_dict["data_provider"].get_position_info.return_value = None
        sys_dict["data_provider"].get_mark_price.return_value = 69500.0

        monitor_open_trades(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.get(mission_id)
        assert "pnl" in mission.meta
        assert mission.meta["pnl"] > 0   # LONG closed above entry


# ─────────────────────────────────────────────────────────────────────────────
# Path 2: Risk-blocked abort
# ─────────────────────────────────────────────────────────────────────────────
class TestRiskBlockedPath:

    def test_mission_closes_on_risk_block(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=False, exec_success=True)
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        all_missions = tracker.list(limit=10)
        assert len(all_missions) == 1
        assert all_missions[0]["stage"] == "CLOSED"

    def test_risk_blocked_mission_never_reaches_execution(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=False, exec_success=True)
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.list(limit=1)[0]
        stages_seen = [h["stage"] for h in mission["history"]]
        assert "EXECUTION" not in stages_seen
        assert stages_seen == ["SIGNAL_FOUND", "VALIDATION", "CLOSED"]

    def test_risk_blocked_clears_current_mission_id(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=False, exec_success=True)
        run_trading_cycle(sys_dict)
        assert sys_dict["current_mission_id"] is None

    def test_execute_trade_never_called_when_risk_blocked(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=False, exec_success=True)
        run_trading_cycle(sys_dict)
        sys_dict["trade_manager"].execute_trade.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Path 3: Execution-failed abort
# ─────────────────────────────────────────────────────────────────────────────
class TestExecutionFailedPath:

    def test_mission_closes_on_execution_failure(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=False)
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.list(limit=1)[0]
        assert mission["stage"] == "CLOSED"

    def test_execution_failed_passes_through_risk_check_stage(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=False)
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        mission = tracker.list(limit=1)[0]
        stages_seen = [h["stage"] for h in mission["history"]]
        assert stages_seen == ["SIGNAL_FOUND", "VALIDATION", "RISK_CHECK", "CLOSED"]

    def test_execution_failed_clears_current_mission_id(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=False)
        run_trading_cycle(sys_dict)
        assert sys_dict["current_mission_id"] is None


# ─────────────────────────────────────────────────────────────────────────────
# WAIT action: no mission created
# ─────────────────────────────────────────────────────────────────────────────
class TestWaitActionNoMission:

    def test_no_mission_created_on_wait(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="WAIT", risk_ok=True, exec_success=True)
        run_trading_cycle(sys_dict)
        tracker = sys_dict["mission_tracker"]
        assert tracker.list(limit=10) == []


# ─────────────────────────────────────────────────────────────────────────────
# Defensive contract: tracker failures never break the trading loop
# ─────────────────────────────────────────────────────────────────────────────
class TestDefensiveContract:

    def test_broken_tracker_create_does_not_raise(self):
        """If mission_tracker.create() raises, run_trading_cycle must still
        complete normally (trade execution must not be blocked by telemetry
        infrastructure failures)."""
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=True, exec_success=True)

        broken_tracker = MagicMock()
        broken_tracker.create.side_effect = RuntimeError("simulated tracker failure")
        sys_dict["mission_tracker"] = broken_tracker

        # Must not raise
        run_trading_cycle(sys_dict)

        # Trade execution still happened despite tracker failure
        sys_dict["trade_manager"].execute_trade.assert_called_once()

    def test_broken_tracker_advance_does_not_raise(self):
        from main import run_trading_cycle
        sys_dict = _make_sys_dict(decision_action="LONG", risk_ok=False, exec_success=True)

        from missions.mission_tracker import MissionTracker
        real_tracker = MissionTracker()
        # Patch advance to fail after create succeeds
        original_advance = real_tracker.advance
        call_count = {"n": 0}
        def flaky_advance(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] >= 2:
                raise RuntimeError("simulated advance failure")
            return original_advance(*args, **kwargs)
        real_tracker.advance = flaky_advance
        sys_dict["mission_tracker"] = real_tracker

        # Must not raise even though advance() fails partway through
        run_trading_cycle(sys_dict)
