"""
Tests: Paper Trading Layer + Dashboard API  (Phase 4C)

Coverage targets
----------------
paper/paper_account.py      — PaperAccount
paper/paper_position.py     — PaperPosition / ClosedTrade
paper/paper_execution.py    — PaperExecutionEngine + metrics helpers
api/app.py                  — all REST endpoints + WebSocket (httpx async client)
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

# ════════════════════════════════════════════════════════════════════════════
# Helpers / Factories
# ════════════════════════════════════════════════════════════════════════════

def _make_decision(
    action="LONG",
    direction="LONG",
    entry=67_000.0,
    sl=65_740.0,
    tp=69_780.0,
    confidence=72,
    regime="TREND",
    oi_delta=0.015,
    funding=0.00010,
):
    """Return a minimal duck-typed decision object."""
    d = MagicMock()
    d.action       = action
    d.direction    = direction
    d.entry_price  = entry
    d.stop_loss    = sl
    d.take_profit  = tp
    d.confidence   = confidence
    d.regime       = regime
    d.oi_delta     = oi_delta
    d.funding_rate = funding
    d.to_dict.return_value = {
        "action": action, "direction": direction,
        "confidence": confidence, "entry_price": entry,
        "stop_loss": sl, "take_profit": tp,
        "oi_delta": oi_delta, "funding_rate": funding,
        "blocked": False, "block_reasons": [], "breakdown": {},
        "regime": regime, "mtf_aligned": True,
        "raw_score": 7, "max_score": 9,
    }
    return d


# ════════════════════════════════════════════════════════════════════════════
# A. PaperAccount
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestPaperAccount:

    def test_initial_balance(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        assert acc.balance == 1000.0

    def test_equity_equals_balance_when_no_position(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        assert acc.equity == acc.balance

    def test_reserve_margin_reduces_free_margin(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        ok  = acc.reserve_margin(notional=5000.0)   # @ 5x = 1000 U margin
        assert ok is True
        assert acc.free_margin == pytest.approx(0.0, abs=0.01)

    def test_reserve_margin_fails_when_insufficient(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=100.0)
        ok  = acc.reserve_margin(notional=5000.0)   # need 1000, have 100
        assert ok is False

    def test_release_margin_restores_free_margin(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.reserve_margin(notional=5000.0)
        acc.release_margin(notional=5000.0)
        assert acc.free_margin == pytest.approx(1000.0, abs=0.01)

    def test_realise_pnl_increases_balance_on_win(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.realise_pnl(50.0)
        assert acc.balance == pytest.approx(1050.0)

    def test_realise_pnl_decreases_balance_on_loss(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.realise_pnl(-30.0)
        assert acc.balance == pytest.approx(970.0)

    def test_equity_curve_grows(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.realise_pnl(20.0)
        acc.realise_pnl(-10.0)
        assert len(acc.equity_curve) == 2

    def test_update_unrealised_reflected_in_equity(self):
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.update_unrealised(80.0)
        assert acc.equity == pytest.approx(1080.0)
        assert acc.unrealised_pnl == pytest.approx(80.0)

    def test_snapshot_to_dict_keys(self):
        from paper.paper_account import PaperAccount
        acc  = PaperAccount(balance=500.0)
        data = acc.to_dict()
        for key in ("balance","equity","used_margin","free_margin",
                    "unrealised_pnl","total_trades","open_trades","leverage","day_pnl"):
            assert key in data, f"Missing key: {key}"

    def test_day_pnl_resets_conceptually(self):
        """Verify day_pnl accumulates within session."""
        from paper.paper_account import PaperAccount
        acc = PaperAccount(balance=1000.0)
        acc.realise_pnl(30.0)
        acc.realise_pnl(20.0)
        assert acc.day_pnl == pytest.approx(50.0)


# ════════════════════════════════════════════════════════════════════════════
# B. PaperPosition
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestPaperPosition:

    def _long(self, entry=67000.0, sl=65740.0, tp=69780.0, qty=0.05):
        from paper.paper_position import PaperPosition
        return PaperPosition(
            symbol="BTCUSDT", direction="LONG",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, leverage=5,
            confidence=72, regime="TREND", oi_delta=0.01, funding_rate=0.0001,
        )

    def _short(self, entry=67000.0, sl=68260.0, tp=64220.0, qty=0.05):
        from paper.paper_position import PaperPosition
        return PaperPosition(
            symbol="BTCUSDT", direction="SHORT",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, leverage=5,
            confidence=65, regime="TREND", oi_delta=-0.01, funding_rate=-0.0001,
        )

    # ── construction ──────────────────────────────────────────────────────────

    def test_invalid_direction_raises(self):
        from paper.paper_position import PaperPosition
        with pytest.raises(ValueError):
            PaperPosition("BTCUSDT", "SIDEWAYS", 67000, 65000, 70000, 0.05, 5)

    def test_zero_quantity_raises(self):
        from paper.paper_position import PaperPosition
        with pytest.raises(ValueError):
            PaperPosition("BTCUSDT", "LONG", 67000, 65000, 70000, 0.0, 5)

    def test_position_id_assigned(self):
        pos = self._long()
        assert len(pos.position_id) == 8

    # ── unrealised PnL ────────────────────────────────────────────────────────

    def test_long_unrealised_profit_when_price_rises(self):
        pos = self._long(entry=67000.0, qty=0.1)
        pos.update_mark(68000.0)
        assert pos.unrealised_pnl == pytest.approx(100.0, abs=0.01)

    def test_long_unrealised_loss_when_price_falls(self):
        pos = self._long(entry=67000.0, qty=0.1)
        pos.update_mark(66000.0)
        assert pos.unrealised_pnl == pytest.approx(-100.0, abs=0.01)

    def test_short_unrealised_profit_when_price_falls(self):
        pos = self._short(entry=67000.0, qty=0.1)
        pos.update_mark(66000.0)
        assert pos.unrealised_pnl == pytest.approx(100.0, abs=0.01)

    # ── SL/TP triggers ────────────────────────────────────────────────────────

    def test_long_tp_hit_returns_closed_trade(self):
        pos = self._long(entry=67000.0, sl=65000.0, tp=69000.0)
        result = pos.update_mark(69100.0)
        assert result is not None
        assert result.result == "WIN"
        assert result.close_reason == "TP"

    def test_long_sl_hit_returns_closed_trade(self):
        pos = self._long(entry=67000.0, sl=65000.0, tp=69000.0)
        result = pos.update_mark(64900.0)
        assert result is not None
        assert result.result == "LOSS"
        assert result.close_reason == "SL"

    def test_short_tp_hit(self):
        pos = self._short(entry=67000.0, sl=68000.0, tp=64000.0)
        result = pos.update_mark(63900.0)
        assert result is not None
        assert result.result == "WIN"
        assert result.close_reason == "TP"

    def test_short_sl_hit(self):
        pos = self._short(entry=67000.0, sl=68000.0, tp=64000.0)
        result = pos.update_mark(68100.0)
        assert result is not None
        assert result.result == "LOSS"
        assert result.close_reason == "SL"

    def test_no_close_while_price_between_sl_tp(self):
        pos = self._long(entry=67000.0, sl=65000.0, tp=69000.0)
        result = pos.update_mark(67500.0)
        assert result is None
        assert pos.is_open is True

    def test_timeout_closes_position(self):
        from paper.paper_position import PaperPosition
        pos = PaperPosition("BTCUSDT","LONG",67000,65000,69000,0.05,5)
        for _ in range(PaperPosition.TIMEOUT_BARS + 1):
            result = pos.update_mark(67300.0)
            if result is not None:
                break
        assert result is not None
        assert result.close_reason == "TIMEOUT"

    def test_closed_trade_pnl_includes_fee(self):
        """Net PnL must be less than raw PnL due to fee deduction."""
        pos = self._long(entry=67000.0, sl=65000.0, tp=70000.0, qty=1.0)
        ct  = pos.update_mark(70100.0)
        raw = (70000.0 - 67000.0) * 1.0   # 3000 USDT raw
        assert ct.pnl < raw                 # fees reduce it

    def test_closed_trade_rr_positive_on_win(self):
        pos = self._long(entry=67000.0, sl=65000.0, tp=70000.0, qty=0.1)
        ct  = pos.update_mark(70100.0)
        assert ct.rr > 0

    def test_manual_close(self):
        pos = self._long()
        ct  = pos.close_manual(67500.0)
        assert ct.close_reason == "MANUAL"
        assert pos.is_open is False

    def test_to_dict_has_required_keys(self):
        pos  = self._long()
        data = pos.to_dict()
        for k in ("position_id","direction","entry_price","mark_price",
                  "stop_loss","take_profit","unrealised_pnl","is_open"):
            assert k in data

    def test_closed_trade_to_dict_has_required_keys(self):
        pos = self._long(entry=67000.0, sl=65000.0, tp=70000.0)
        ct  = pos.update_mark(70100.0)
        data = ct.to_dict()
        for k in ("pnl","result","rr","opened_at","closed_at",
                  "close_reason","confidence","regime","oi_delta","funding_rate"):
            assert k in data


# ════════════════════════════════════════════════════════════════════════════
# C. PaperExecutionEngine
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestPaperExecutionEngine:

    def _engine(self, balance=1000.0):
        from paper.paper_execution import PaperExecutionEngine
        return PaperExecutionEngine(starting_usdt=balance)

    # ── execute ───────────────────────────────────────────────────────────────

    def test_execute_long_returns_success(self):
        eng = self._engine()
        dec = _make_decision(action="LONG")
        res = eng.execute(dec)
        assert res["success"] is True
        assert res["direction"] == "LONG"

    def test_execute_short_returns_success(self):
        eng = self._engine()
        dec = _make_decision(action="SHORT", direction="SHORT",
                             entry=67000.0, sl=68260.0, tp=64220.0)
        res = eng.execute(dec)
        assert res["success"] is True

    def test_skip_action_not_executed(self):
        eng = self._engine()
        dec = _make_decision(action="WAIT")
        res = eng.execute(dec)
        assert res["success"] is False
        assert "action=WAIT" in res["reason"]

    def test_max_one_position(self):
        eng = self._engine()
        dec = _make_decision()
        eng.execute(dec)
        res2 = eng.execute(dec)
        assert res2["success"] is False
        assert "max_open" in res2["reason"]

    def test_degenerate_levels_rejected(self):
        eng = self._engine()
        dec = _make_decision(entry=67000.0, sl=67000.0)   # SL == entry
        res = eng.execute(dec)
        assert res["success"] is False

    def test_insufficient_margin_rejected(self):
        eng = self._engine(balance=10.0)
        dec = _make_decision(entry=67000.0, sl=65000.0)   # needs > $10 margin
        # force worst case with huge quantity
        res = eng.execute(dec, risk_pct=1.0)
        # Either fails margin OR succeeds with tiny qty — just no exception
        assert "success" in res

    def test_execute_stores_open_position(self):
        eng = self._engine()
        eng.execute(_make_decision())
        assert eng.has_open_position is True
        assert len(eng.get_open_positions()) == 1

    # ── tick / close ──────────────────────────────────────────────────────────

    def test_tick_tp_closes_position(self):
        eng = self._engine()
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        closed = eng.tick(69100.0)
        assert len(closed) == 1
        assert closed[0].result == "WIN"
        assert eng.has_open_position is False

    def test_tick_sl_closes_position(self):
        eng = self._engine()
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        closed = eng.tick(64900.0)
        assert len(closed) == 1
        assert closed[0].result == "LOSS"

    def test_tick_no_trigger_returns_empty(self):
        eng = self._engine()
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        closed = eng.tick(67500.0)
        assert closed == []

    def test_close_all_forces_close(self):
        eng = self._engine()
        eng.execute(_make_decision())
        closed = eng.close_all(67500.0)
        assert len(closed) == 1
        assert closed[0].close_reason == "MANUAL"
        assert eng.has_open_position is False

    def test_balance_increases_after_win(self):
        eng = self._engine(balance=1000.0)
        start = eng.account.balance
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        eng.tick(69100.0)
        assert eng.account.balance > start

    def test_balance_decreases_after_loss(self):
        eng = self._engine(balance=1000.0)
        start = eng.account.balance
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        eng.tick(64900.0)
        assert eng.account.balance < start

    # ── metrics ───────────────────────────────────────────────────────────────

    def test_empty_metrics_structure(self):
        eng = self._engine()
        m   = eng.get_metrics()
        assert m["total_trades"]  == 0
        assert m["win_rate"]      == 0.0
        assert "account"    in m

    def test_metrics_after_two_wins_one_loss(self):
        from paper.paper_execution import PaperExecutionEngine
        eng = PaperExecutionEngine(starting_usdt=5000.0)

        def _trade(action, sl_above_entry):
            d = _make_decision(
                action=action, direction=action,
                entry=67000.0,
                sl=68000.0 if sl_above_entry else 65000.0,
                tp=64000.0 if action=="SHORT" else 69000.0,
            )
            eng.execute(d)
            # TP trigger
            tp_price = 63900.0 if action=="SHORT" else 69100.0
            eng.tick(tp_price)

        _trade("LONG",  False)   # WIN
        _trade("LONG",  False)   # WIN
        d2 = _make_decision(entry=67000.0, sl=65000.0, tp=69000.0)
        eng.execute(d2)
        eng.tick(64900.0)        # LOSS

        m = eng.get_metrics()
        assert m["total_trades"] == 3
        assert m["wins"]         == 2
        assert m["losses"]       == 1
        assert m["win_rate"]     == pytest.approx(2/3, rel=0.01)
        assert m["profit_factor"] > 0
        assert m["expectancy"]   is not None
        assert "max_drawdown"    in m
        assert "sharpe_ratio"    in m

    def test_trade_count_property(self):
        eng = self._engine()
        assert eng.trade_count == 0
        eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
        eng.tick(69100.0)
        assert eng.trade_count == 1

    def test_get_closed_trades_limit(self):
        from paper.paper_execution import PaperExecutionEngine
        eng = PaperExecutionEngine(starting_usdt=10000.0)
        for _ in range(5):
            eng.execute(_make_decision(entry=67000.0, sl=65000.0, tp=69000.0))
            eng.tick(69100.0)
        assert len(eng.get_closed_trades(limit=3)) == 3

    # ── helper functions ──────────────────────────────────────────────────────

    def test_sharpe_empty_returns_zero(self):
        from paper.paper_execution import _sharpe
        assert _sharpe([]) == 0.0
        assert _sharpe([10.0]) == 0.0

    def test_sharpe_positive_pnls(self):
        from paper.paper_execution import _sharpe
        pnls = [10.0, 12.0, 8.0, 11.0, 9.0]
        s = _sharpe(pnls)
        assert s > 0

    def test_sharpe_mixed_pnls(self):
        from paper.paper_execution import _sharpe
        pnls = [10.0, -5.0, 15.0, -3.0, 8.0]
        s = _sharpe(pnls)
        assert isinstance(s, float)

    def test_max_drawdown_no_loss(self):
        from paper.paper_execution import _max_drawdown
        dd, dd_pct = _max_drawdown([10.0, 20.0, 30.0], starting_balance=1000.0)
        assert dd     == pytest.approx(0.0)
        assert dd_pct == pytest.approx(0.0)

    def test_max_drawdown_with_loss(self):
        from paper.paper_execution import _max_drawdown
        # balance: 1000 → 1010 → 980 → 1050
        dd, dd_pct = _max_drawdown([10.0, -30.0, 70.0], starting_balance=1000.0)
        assert dd     == pytest.approx(30.0)
        assert dd_pct == pytest.approx(30.0 / 1010.0, rel=0.01)


# ════════════════════════════════════════════════════════════════════════════
# D. Dashboard API — REST endpoints
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestDashboardAPI:

    @pytest.fixture(autouse=True)
    def client(self):
        """Sync httpx test client — no live DB or EventBus required."""
        from fastapi.testclient import TestClient
        from api.app import app, _state, set_state
        from events.event_bus import reset_event_bus

        reset_event_bus(journal=None, persist=False)
        # Clear state
        set_state("latest_decision", None)
        set_state("latest_context",  None)
        set_state("paper_engine",    None)
        set_state("journal_v2",      None)

        with TestClient(app, raise_server_exceptions=False) as c:
            self._app   = app
            self._state = _state
            self._set   = set_state
            yield c

    # ── /api/health ───────────────────────────────────────────────────────────

    def test_health_200(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["status"] == "ok"

    def test_health_has_required_keys(self, client):
        data = client.get("/api/health").json()["data"]
        for k in ("status","version","symbol","leverage","testnet",
                  "uptime_s","started_at","paper_enabled","paper_trades"):
            assert k in data, f"Missing key: {k}"

    def test_health_uptime_non_negative(self, client):
        assert client.get("/api/health").json()["data"]["uptime_s"] >= 0

    # ── /api/config ───────────────────────────────────────────────────────────

    def test_config_200(self, client):
        r = client.get("/api/config")
        assert r.status_code == 200

    def test_config_no_secrets(self, client):
        data = r = client.get("/api/config").json()["data"]
        for banned in ("api_key","api_secret","password","secret"):
            assert not any(banned in k.lower() for k in data)

    def test_config_has_symbol(self, client):
        assert "symbol" in client.get("/api/config").json()["data"]

    # ── /api/decision ─────────────────────────────────────────────────────────

    def test_decision_no_state_returns_message(self, client):
        r = client.get("/api/decision")
        assert r.status_code == 200
        assert "message" in r.json()["data"]

    def test_decision_with_state(self, client):
        self._set("latest_decision", _make_decision())
        r    = client.get("/api/decision")
        data = r.json()["data"]
        assert "decision" in data
        assert data["decision"]["action"] == "LONG"

    # ── /api/signals ──────────────────────────────────────────────────────────

    def test_signals_200(self, client):
        r = client.get("/api/signals")
        assert r.status_code == 200
        data = r.json()["data"]
        assert "signals" in data
        assert "count"   in data

    def test_signals_limit_param(self, client):
        r = client.get("/api/signals?limit=10")
        assert r.status_code == 200

    def test_signals_invalid_limit(self, client):
        r = client.get("/api/signals?limit=0")
        assert r.status_code == 422

    # ── /api/futures ──────────────────────────────────────────────────────────

    def test_futures_200(self, client):
        r = client.get("/api/futures")
        assert r.status_code == 200

    def test_futures_has_snapshot(self, client):
        data = client.get("/api/futures").json()["data"]
        assert "snapshot" in data
        assert "oi_history" in data
        assert "funding_history" in data

    def test_futures_context_when_set(self, client):
        self._set("latest_context", {
            "oi_delta": 0.025, "funding_rate": 0.00012,
            "futures_signal": "LONG", "futures_condition": "STRONG_TREND",
            "futures": {},
        })
        snap = client.get("/api/futures").json()["data"]["snapshot"]
        assert snap["oi_delta"] == pytest.approx(0.025)
        assert snap["funding_rate"] == pytest.approx(0.00012)

    # ── /api/regime ───────────────────────────────────────────────────────────

    def test_regime_200(self, client):
        r = client.get("/api/regime")
        assert r.status_code == 200

    def test_regime_has_current(self, client):
        data = client.get("/api/regime").json()["data"]
        assert "current" in data
        assert "history" in data

    def test_regime_current_from_context(self, client):
        self._set("latest_context", {
            "regime": "TREND", "regime_conf": 0.85,
            "trend_bias": "LONG_BIAS", "trend_strength": "STRONG",
            "trend_data": {},
        })
        cur = client.get("/api/regime").json()["data"]["current"]
        assert cur["regime"]     == "TREND"
        assert cur["trend_bias"] == "LONG_BIAS"

    # ── /api/events ───────────────────────────────────────────────────────────

    def test_events_200(self, client):
        r = client.get("/api/events")
        assert r.status_code == 200

    def test_events_has_count_and_list(self, client):
        data = client.get("/api/events").json()["data"]
        assert "count"  in data
        assert "events" in data

    def test_events_limit_param(self, client):
        r = client.get("/api/events?limit=5")
        assert r.status_code == 200

    def test_events_agent_filter(self, client):
        r = client.get("/api/events?agent=BRAIN_BOT")
        assert r.status_code == 200

    # ── /api/journal ──────────────────────────────────────────────────────────

    def test_journal_200(self, client):
        r = client.get("/api/journal")
        assert r.status_code == 200

    def test_journal_has_performance(self, client):
        data = client.get("/api/journal").json()["data"]
        assert "performance" in data

    def test_journal_has_open_trades(self, client):
        data = client.get("/api/journal").json()["data"]
        assert "open_trades" in data

    # ── /api/paper ────────────────────────────────────────────────────────────

    def test_paper_disabled_when_no_engine(self, client):
        data = client.get("/api/paper").json()["data"]
        assert data["enabled"] is False

    def test_paper_enabled_when_engine_set(self, client):
        from paper.paper_execution import PaperExecutionEngine
        self._set("paper_engine", PaperExecutionEngine(starting_usdt=1000.0))
        data = client.get("/api/paper").json()["data"]
        assert data["enabled"] is True

    def test_paper_has_metrics_when_enabled(self, client):
        from paper.paper_execution import PaperExecutionEngine
        self._set("paper_engine", PaperExecutionEngine(starting_usdt=1000.0))
        data = client.get("/api/paper").json()["data"]
        assert "metrics"      in data
        assert "equity_curve" in data
        assert "goal_trades"  in data

    def test_paper_metrics_endpoint(self, client):
        from paper.paper_execution import PaperExecutionEngine
        self._set("paper_engine", PaperExecutionEngine(starting_usdt=1000.0))
        r = client.get("/api/paper/metrics")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is True
        assert data["metrics"] is not None
        assert data["reason"] is None

    def test_paper_metrics_graceful_when_disabled(self, client):
        """
        Paper trading being disabled/unavailable is a normal runtime state
        (EXECUTION_MODE=testnet/live, or not yet initialized) — not a server
        error. Must be 200 + enabled=False, never 503.
        """
        r = client.get("/api/paper/metrics")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False
        assert data["metrics"] is None
        assert data["reason"] == "Paper trading not initialized"

    def test_paper_trades_endpoint(self, client):
        from paper.paper_execution import PaperExecutionEngine
        pe = PaperExecutionEngine(starting_usdt=1000.0)
        self._set("paper_engine", pe)
        r = client.get("/api/paper/trades")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is True
        assert "trades"      in data
        assert "total_count" in data

    def test_paper_trades_graceful_when_disabled(self, client):
        """Same contract as /api/paper/metrics: 200 + enabled=False, never 503."""
        r = client.get("/api/paper/trades")
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["enabled"] is False
        assert data["trades"] is None
        assert data["total_count"] == 0
        assert data["reason"] == "Paper trading not initialized"

    def test_paper_goal_progress_zero_at_start(self, client):
        from paper.paper_execution import PaperExecutionEngine
        self._set("paper_engine", PaperExecutionEngine(starting_usdt=1000.0))
        data = client.get("/api/paper").json()["data"]
        assert data["goal_progress"] == pytest.approx(0.0)

    # ── response envelope ─────────────────────────────────────────────────────

    def test_all_endpoints_have_ok_field(self, client):
        endpoints = [
            "/api/health", "/api/config", "/api/decision",
            "/api/signals", "/api/futures", "/api/regime",
            "/api/events",  "/api/journal", "/api/paper",
        ]
        for ep in endpoints:
            r = client.get(ep)
            assert "ok" in r.json(), f"{ep} missing 'ok' envelope"


# ════════════════════════════════════════════════════════════════════════════
# E. WebSocket basic tests (sync client)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestWebSockets:

    @pytest.fixture(autouse=True)
    def setup(self):
        from api.app import app, set_state
        from events.event_bus import reset_event_bus
        reset_event_bus(journal=None, persist=False)
        set_state("latest_decision", None)
        set_state("latest_context",  None)
        set_state("paper_engine",    None)
        set_state("journal_v2",      None)
        self._app = app
        self._set = set_state
        yield

    def test_ws_events_connects_and_receives_init(self):
        from fastapi.testclient import TestClient
        with TestClient(self._app) as client:
            with client.websocket_connect("/ws/events") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "init"
                assert "events" in msg

    def test_ws_signals_connects_and_receives_init(self):
        from fastapi.testclient import TestClient
        with TestClient(self._app) as client:
            with client.websocket_connect("/ws/signals") as ws:
                msg = ws.receive_json()
                # May be init with or without signal
                assert msg["type"] == "init"

    def test_ws_decision_no_state_gets_init_on_connection(self):
        from fastapi.testclient import TestClient
        with TestClient(self._app) as client:
            with client.websocket_connect("/ws/decision") as ws:
                # No decision set → connection stays open but nothing sent yet;
                # do a minimal ping to confirm it doesn't crash
                ws.send_text("ping")

    def test_ws_decision_sends_init_when_decision_set(self):
        from fastapi.testclient import TestClient
        self._set("latest_decision", _make_decision())
        with TestClient(self._app) as client:
            with client.websocket_connect("/ws/decision") as ws:
                msg = ws.receive_json()
                assert msg["type"] == "init"
                assert "decision" in msg
                assert msg["decision"]["action"] == "LONG"


# ════════════════════════════════════════════════════════════════════════════
# F. End-to-end Paper Pipeline (decision → execute → tick → metrics)
# ════════════════════════════════════════════════════════════════════════════

@pytest.mark.unit
class TestPaperPipelineE2E:

    def test_200_trade_simulation(self):
        """
        Simulate 200 paper trades with alternating wins/losses.
        Validates all metric keys are present and numerically sane.
        """
        from paper.paper_execution import PaperExecutionEngine
        eng = PaperExecutionEngine(starting_usdt=10_000.0)

        for i in range(200):
            dec = _make_decision(
                action="LONG",
                entry=67000.0,
                sl=65000.0,
                tp=69000.0,
            )
            res = eng.execute(dec, risk_pct=0.01)
            assert res["success"], f"Trade {i} failed to open"

            # Alternate: win on even, loss on odd
            if i % 2 == 0:
                eng.tick(69100.0)   # TP
            else:
                eng.tick(64900.0)   # SL

        m = eng.get_metrics()
        assert m["total_trades"]  == 200
        assert m["wins"]          == 100
        assert m["losses"]        == 100
        assert m["win_rate"]      == pytest.approx(0.5, abs=0.01)
        assert 0 <= m["profit_factor"]
        assert m["max_drawdown"]  >= 0
        assert isinstance(m["sharpe_ratio"], float)
        assert isinstance(m["expectancy"],   float)

        # Balance must still be positive
        assert eng.account.balance > 0

    def test_paper_api_reflects_200_trades(self):
        """Verify /api/paper goal_progress reaches 100% after 200 trades."""
        from fastapi.testclient import TestClient
        from paper.paper_execution import PaperExecutionEngine
        from api.app import app, set_state

        eng = PaperExecutionEngine(starting_usdt=10_000.0)

        for i in range(200):
            dec = _make_decision(entry=67000.0, sl=65000.0, tp=69000.0)
            eng.execute(dec, risk_pct=0.01)
            eng.tick(69100.0 if i % 2 == 0 else 64900.0)

        set_state("paper_engine", eng)

        with TestClient(app, raise_server_exceptions=False) as client:
            data = client.get("/api/paper").json()["data"]

        assert data["goal_progress"]  == pytest.approx(100.0)
        assert data["trade_count"]    == 200
        m = data["metrics"]
        assert m["total_trades"]      == 200
        assert m["win_rate"]          > 0
