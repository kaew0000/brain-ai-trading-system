"""
tests/test_commander.py
==========================
v14 Phase 2.5 — Commander Interface test suite.

Covers:
  - TradingControlState (pause/resume/paper_mode_forced flags)
  - CommanderService command parsing (token-based, all 7 commands + edge cases)
  - Read-only command handlers (positions/pnl/risk) with fake context
  - main.py wiring: pause check skips run_trading_cycle; paper_mode_forced
    skips real execution and closes the mission with a clear note
  - POST /api/command, GET /api/command/state
  - WS /ws/command (bidirectional, always sends init, no duplicate replies)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_control_state():
    from commander.control_state import reset_control_state
    reset_control_state()
    yield
    reset_control_state()


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


# ─────────────────────────────────────────────────────────────────────────────
# TradingControlState
# ─────────────────────────────────────────────────────────────────────────────
class TestControlState:

    def test_default_not_paused(self):
        from commander.control_state import get_control_state
        assert get_control_state().is_paused() is False

    def test_pause_sets_flag(self):
        from commander.control_state import get_control_state
        s = get_control_state()
        s.pause()
        assert s.is_paused() is True

    def test_resume_clears_flag(self):
        from commander.control_state import get_control_state
        s = get_control_state()
        s.pause()
        s.resume()
        assert s.is_paused() is False

    def test_default_paper_mode_forced_none(self):
        from commander.control_state import get_control_state
        assert get_control_state().get_paper_mode_forced() is None

    def test_set_paper_mode_forced_true(self):
        from commander.control_state import get_control_state
        s = get_control_state()
        s.set_paper_mode_forced(True)
        assert s.get_paper_mode_forced() is True

    def test_set_paper_mode_forced_false(self):
        from commander.control_state import get_control_state
        s = get_control_state()
        s.set_paper_mode_forced(False)
        assert s.get_paper_mode_forced() is False

    def test_snapshot_has_three_keys(self):
        from commander.control_state import get_control_state
        snap = get_control_state().snapshot()
        assert set(snap.keys()) == {"paused", "paper_mode_forced", "updated_at"}

    def test_reset_clears_everything(self):
        from commander.control_state import get_control_state
        s = get_control_state()
        s.pause()
        s.set_paper_mode_forced(True)
        s.reset()
        assert s.is_paused() is False
        assert s.get_paper_mode_forced() is None

    def test_singleton_persists(self):
        from commander.control_state import get_control_state
        assert get_control_state() is get_control_state()

    def test_thread_safety(self):
        from commander.control_state import get_control_state
        import threading
        s = get_control_state()

        def toggler():
            for _ in range(50):
                s.pause()
                s.resume()

        threads = [threading.Thread(target=toggler) for _ in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        # No assertion on final state (race-inherent) — just must not crash


# ─────────────────────────────────────────────────────────────────────────────
# CommanderService — command parsing
# ─────────────────────────────────────────────────────────────────────────────
class TestCommandParsing:

    def test_pause_trader_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("pause trader")
        assert result.matched == "pause_trader"
        assert result.success is True

    def test_resume_trader_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("resume trader")
        assert result.matched == "resume_trader"

    def test_paper_mode_on_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("paper mode on")
        assert result.matched == "paper_mode_on"

    def test_paper_mode_off_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("paper mode off")
        assert result.matched == "paper_mode_off"

    def test_show_positions_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show positions")
        assert result.matched == "show_positions"

    def test_show_pnl_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show pnl")
        assert result.matched == "show_pnl"

    def test_show_risk_matches(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show risk")
        assert result.matched == "show_risk"

    def test_case_insensitive(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("PAUSE TRADER")
        assert result.matched == "pause_trader"

    def test_extra_words_still_match(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("please pause the trader right now")
        assert result.matched == "pause_trader"

    def test_unrecognized_command_returns_failure(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("do a backflip")
        assert result.success is False
        assert result.matched == ""
        assert "Unrecognized" in result.message

    def test_empty_command_returns_failure(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("")
        assert result.success is False

    def test_none_command_does_not_raise(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute(None)
        assert result.success is False

    def test_paper_mode_on_does_not_falsely_match_off(self):
        """Regression guard: 'on' is not a substring of 'off' so no
        false-positive cross-matching between the two paper-mode commands."""
        from commander.commander_service import CommanderService
        result = CommanderService().execute("paper mode off")
        assert result.matched == "paper_mode_off"
        assert result.data["paper_mode_forced"] is False

    def test_noon_does_not_falsely_match_on(self):
        """Token-based matching (not substring) — 'noon' must not trigger
        any paper-mode command even though it contains 'on' as a substring."""
        from commander.commander_service import CommanderService
        result = CommanderService().execute("remind me at noon")
        assert result.success is False


# ─────────────────────────────────────────────────────────────────────────────
# CommanderService — mutating commands actually mutate state
# ─────────────────────────────────────────────────────────────────────────────
class TestMutatingCommands:

    def test_pause_trader_sets_control_state(self):
        from commander.commander_service import CommanderService
        from commander.control_state import get_control_state
        CommanderService().execute("pause trader")
        assert get_control_state().is_paused() is True

    def test_resume_trader_clears_control_state(self):
        from commander.commander_service import CommanderService
        from commander.control_state import get_control_state
        get_control_state().pause()
        CommanderService().execute("resume trader")
        assert get_control_state().is_paused() is False

    def test_paper_mode_on_sets_control_state(self):
        from commander.commander_service import CommanderService
        from commander.control_state import get_control_state
        CommanderService().execute("paper mode on")
        assert get_control_state().get_paper_mode_forced() is True

    def test_paper_mode_off_sets_control_state(self):
        from commander.commander_service import CommanderService
        from commander.control_state import get_control_state
        CommanderService().execute("paper mode off")
        assert get_control_state().get_paper_mode_forced() is False


# ─────────────────────────────────────────────────────────────────────────────
# Read-only commands
# ─────────────────────────────────────────────────────────────────────────────
class TestShowPositions:

    def test_no_context_returns_empty(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show positions", context={})
        assert result.success is True
        assert result.data["positions"] == []

    def test_paper_engine_open_positions(self):
        from commander.commander_service import CommanderService
        paper_engine = MagicMock()
        paper_engine.get_open_positions.return_value = [
            {"direction": "LONG", "symbol": "BTCUSDT", "quantity": 0.1, "entry_price": 67000.0}
        ]
        result = CommanderService().execute("show positions", context={"paper_engine": paper_engine})
        assert len(result.data["positions"]) == 1
        assert "LONG" in result.message

    def test_live_position_info(self):
        from commander.commander_service import CommanderService
        position_info = {"side": "SHORT", "positionAmt": "-0.2",
                          "entryPrice": 68000.0, "unrealizedProfit": -12.5}
        result = CommanderService().execute("show positions",
                                             context={"position_info": position_info})
        assert "SHORT" in result.message


class TestShowPnl:

    def test_no_context_returns_message(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show pnl", context={})
        assert result.success is True

    def test_paper_engine_metrics(self):
        from commander.commander_service import CommanderService
        paper_engine = MagicMock()
        paper_engine.get_metrics.return_value = {
            "total_pnl": 125.50, "win_rate": 0.6, "total_trades": 10,
        }
        result = CommanderService().execute("show pnl", context={"paper_engine": paper_engine})
        assert "125.50" in result.message
        assert result.data["total_trades"] == 10

    def test_journal_fallback_when_no_paper_engine(self):
        from commander.commander_service import CommanderService
        journal = MagicMock()
        journal.get_performance_summary.return_value = {"total_trades": 5}
        result = CommanderService().execute("show pnl", context={"journal_v2": journal})
        assert result.success is True


class TestShowRisk:

    def test_no_context_returns_message(self):
        from commander.commander_service import CommanderService
        result = CommanderService().execute("show risk", context={})
        assert result.success is True

    def test_risk_report_allowed(self):
        from commander.commander_service import CommanderService
        risk_report = {
            "can_trade": True, "today_pnl": 50.0,
            "consecutive_losses": 0, "dynamic_risk_pct": 0.01,
        }
        result = CommanderService().execute("show risk", context={"risk_report": risk_report})
        assert "ALLOWED" in result.message

    def test_risk_report_blocked(self):
        from commander.commander_service import CommanderService
        risk_report = {
            "can_trade": False, "today_pnl": -350.0,
            "consecutive_losses": 3, "dynamic_risk_pct": 0.005,
            "block_reason": "Daily loss limit exceeded",
        }
        result = CommanderService().execute("show risk", context={"risk_report": risk_report})
        assert "BLOCKED" in result.message
        assert "Daily loss limit exceeded" in result.message


# ─────────────────────────────────────────────────────────────────────────────
# main.py wiring: pause check + paper-mode-forced safety override
# ─────────────────────────────────────────────────────────────────────────────
class TestMainPyWiring:

    def _make_minimal_sys_dict(self):
        """Reuses the same mock-building approach as test_mission_pipeline_integration.py."""
        from missions.mission_tracker import get_mission_tracker
        from features.smc_engine import SMCSignals
        from features.volume_engine import VolumeSignals
        from events.event_bus import get_event_bus

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
        reg = MagicMock(); reg.classify.return_value = regime_result

        smc = MagicMock()
        smc.analyze_mtf.return_value = {"m15": SMCSignals(), "h1": SMCSignals(), "h4": SMCSignals()}
        vol = MagicMock(); vol.analyze.return_value = VolumeSignals()

        ctxb = MagicMock()
        ctxb.build.return_value = {
            "mtf_direction": "LONG", "mtf_aligned": True,
            "mark_price": 67000.0, "regime": "TREND", "futures": {},
        }

        decision = MagicMock()
        decision.action = "LONG"; decision.direction = "LONG"
        decision.entry_price = 67000.0; decision.stop_loss = 65800.0
        decision.take_profit = 69400.0; decision.confidence = 78.0
        decision.regime = "TREND"; decision.oi_delta = 0.012
        decision.funding_rate = 0.0001
        decision.to_dict.return_value = {"action": "LONG", "confidence": 78.0}
        ce = MagicMock(); ce.score.return_value = decision

        expl = MagicMock()
        explanation_result = MagicMock()
        explanation_result.to_dict.return_value = {"summary": "test"}
        expl.explain.return_value = explanation_result

        jrn = MagicMock()
        jrn.get_open_trades.return_value = []
        jrn.save_trade.return_value = 1

        rsk = MagicMock()
        rsk.can_trade.return_value = (True, "")
        rsk.get_risk_pct.return_value = 0.01
        # P1-B1: main.py now also calls rsk.get_leverage(atr_pct=...) every
        # cycle; without this stub it returns an un-comparable MagicMock,
        # which crashes main.py's dynamic-leverage log line.
        rsk.get_leverage.return_value = 5

        tm = MagicMock()
        tm.execute_trade.return_value = {"success": True, "quantity": 0.1,
                                          "entry_order": {"orderId": "1"}}

        return {
            "data_provider": dp, "smc_engine": smc, "volume_engine": vol,
            "regime_engine": reg, "context_builder": ctxb,
            "confidence_engine": ce, "causal_explainer": expl,
            "journal_v2": jrn, "risk_engine": rsk, "trade_manager": tm,
            "event_bus": get_event_bus(), "agent_layer": {},
            "mission_tracker": get_mission_tracker(), "current_mission_id": None,
        }

    def test_paused_skips_cycle_entirely(self):
        from main import run_trading_cycle
        from commander.control_state import get_control_state
        get_control_state().pause()

        sys_dict = self._make_minimal_sys_dict()
        run_trading_cycle(sys_dict)

        sys_dict["data_provider"].get_position_info.assert_not_called()

    def test_not_paused_runs_normally(self):
        from main import run_trading_cycle
        sys_dict = self._make_minimal_sys_dict()
        run_trading_cycle(sys_dict)
        sys_dict["trade_manager"].execute_trade.assert_called_once()

    def test_paper_mode_forced_skips_real_execution(self):
        from main import run_trading_cycle
        from commander.control_state import get_control_state
        get_control_state().set_paper_mode_forced(True)

        sys_dict = self._make_minimal_sys_dict()
        run_trading_cycle(sys_dict)

        sys_dict["trade_manager"].execute_trade.assert_not_called()

    def test_paper_mode_forced_closes_mission_with_clear_note(self):
        from main import run_trading_cycle
        from commander.control_state import get_control_state
        get_control_state().set_paper_mode_forced(True)

        sys_dict = self._make_minimal_sys_dict()
        run_trading_cycle(sys_dict)

        tracker = sys_dict["mission_tracker"]
        missions = tracker.list(limit=10)
        assert len(missions) == 1
        assert missions[0]["stage"] == "CLOSED"
        assert "safety override" in missions[0]["history"][-1]["note"]

    def test_paper_mode_off_allows_real_execution(self):
        from main import run_trading_cycle
        from commander.control_state import get_control_state
        get_control_state().set_paper_mode_forced(False)

        sys_dict = self._make_minimal_sys_dict()
        run_trading_cycle(sys_dict)

        sys_dict["trade_manager"].execute_trade.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# API: POST /api/command, GET /api/command/state
# ─────────────────────────────────────────────────────────────────────────────
class TestCommandAPI:

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_post_command_200(self, client):
        r = client.post("/api/command", json={"command": "show positions"})
        assert r.status_code == 200

    def test_post_command_ok_true(self, client):
        body = client.post("/api/command", json={"command": "show pnl"}).json()
        assert body["ok"] is True

    def test_post_pause_trader_returns_success(self, client):
        body = client.post("/api/command", json={"command": "pause trader"}).json()
        assert body["data"]["success"] is True
        assert body["data"]["matched"] == "pause_trader"

    def test_post_pause_then_resume_round_trip(self, client):
        from commander.control_state import get_control_state
        client.post("/api/command", json={"command": "pause trader"})
        assert get_control_state().is_paused() is True
        client.post("/api/command", json={"command": "resume trader"})
        assert get_control_state().is_paused() is False

    def test_post_unrecognized_command_still_200(self, client):
        """Unrecognised commands are NOT HTTP errors — success=false in the body."""
        r = client.post("/api/command", json={"command": "fly to the moon"})
        assert r.status_code == 200
        assert r.json()["data"]["success"] is False

    def test_post_empty_body(self, client):
        r = client.post("/api/command", json={})
        assert r.status_code == 200
        assert r.json()["data"]["success"] is False

    def test_get_command_state_200(self, client):
        r = client.get("/api/command/state")
        assert r.status_code == 200

    def test_get_command_state_reflects_pause(self, client):
        client.post("/api/command", json={"command": "pause trader"})
        body = client.get("/api/command/state").json()
        assert body["data"]["paused"] is True


# ─────────────────────────────────────────────────────────────────────────────
# WS: /ws/command
# ─────────────────────────────────────────────────────────────────────────────
class TestCommandWebSocket:

    def test_ws_command_sends_init_frame(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/command") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert "paused" in msg["data"]

    def test_ws_command_executes_and_replies(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/command") as ws:
            ws.receive_json()   # init frame
            ws.send_text('{"command": "show positions"}')
            reply = ws.receive_json()
            assert reply["type"] == "command_result"
            assert reply["data"]["matched"] == "show_positions"

    def test_ws_command_no_duplicate_reply(self):
        """Regression test for the self-caught duplicate-broadcast bug:
        sending one command must yield exactly ONE result frame back."""
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/command") as ws:
            ws.receive_json()   # init
            ws.send_text('{"command": "show pnl"}')
            first = ws.receive_json()
            assert first["type"] == "command_result"
            # If the bug were present, a second frame would already be
            # queued here. Send a harmless follow-up and confirm the
            # NEXT frame is for the NEW command, not a leftover duplicate.
            ws.send_text('{"command": "show risk"}')
            second = ws.receive_json()
            assert second["data"]["matched"] == "show_risk"

    def test_ws_command_accepts_bare_string(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/command") as ws:
            ws.receive_json()
            ws.send_text("show positions")   # not JSON — bare string
            reply = ws.receive_json()
            assert reply["data"]["matched"] == "show_positions"

    def test_ws_command_mutates_control_state(self):
        from api.app import app
        from commander.control_state import get_control_state
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/command") as ws:
            ws.receive_json()
            ws.send_text('{"command": "pause trader"}')
            ws.receive_json()
        assert get_control_state().is_paused() is True
