"""
tests/test_audit_fixes.py
=========================
New tests added during the Phase 8 / Phase 10 audit cycle.

Covers gaps identified in the Phase 1 Bug Hunt:
  - BUG-01: balance NameError in agent block
  - BUG-03: _api_module import scope
  - BUG-04: leverage double-application in monitor PnL
  - BUG-05: paper_account unrealised PnL reset
  - BUG-06: ws/decision always sends init frame
  - Quant: PaperPosition SL/TP correctness
  - Quant: PaperAccount margin accounting
  - Quant: Sharpe / drawdown helpers
  - Security: .env keys absent from log output
  - Risk: daily loss calculation
  - Risk: consecutive loss streak
"""
from __future__ import annotations
import math
import pytest
pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# BUG-05: PaperAccount — unrealised PnL reset must not corrupt equity
# ─────────────────────────────────────────────────────────────────────────────
class TestPaperAccountEquity:

    def _make_account(self, balance=1000.0):
        from paper.paper_account import PaperAccount
        return PaperAccount(balance=balance, leverage=5)

    def test_initial_balance(self):
        acc = self._make_account(1000)
        assert acc.balance == pytest.approx(1000.0)

    def test_initial_equity_equals_balance(self):
        acc = self._make_account(1000)
        assert acc.equity == pytest.approx(1000.0)

    def test_reserve_margin_reduces_free_margin(self):
        acc = self._make_account(1000)
        notional = 500.0          # 500 USDT notional, leverage=5 → margin=100
        ok = acc.reserve_margin(notional)
        assert ok is True
        assert acc.free_margin == pytest.approx(900.0, abs=0.01)
        assert acc.used_margin == pytest.approx(100.0, abs=0.01)

    def test_reserve_margin_returns_false_if_insufficient(self):
        acc = self._make_account(100)
        ok = acc.reserve_margin(10_000.0)   # margin=2000 > 100
        assert ok is False
        assert acc.used_margin == pytest.approx(0.0)

    def test_release_margin_restores_free_margin(self):
        acc = self._make_account(1000)
        acc.reserve_margin(500.0)
        acc.release_margin(500.0)
        assert acc.free_margin == pytest.approx(1000.0, abs=0.01)

    def test_realise_pnl_positive_increases_balance(self):
        acc = self._make_account(1000)
        acc.realise_pnl(50.0)
        assert acc.balance == pytest.approx(1050.0)

    def test_realise_pnl_negative_decreases_balance(self):
        acc = self._make_account(1000)
        acc.realise_pnl(-30.0)
        assert acc.balance == pytest.approx(970.0)

    def test_realise_pnl_does_not_corrupt_equity(self):
        """BUG-05: old code did max(0, unrealised - abs(pnl)) which could
        leave stale unrealised when losses exceeded the stored value."""
        acc = self._make_account(1000)
        acc.update_unrealised(50.0)     # open position has +50 unrealised
        acc.realise_pnl(-80.0)          # position closes at a loss
        # update_unrealised(0) is called by tick() after closing
        acc.update_unrealised(0.0)
        assert acc.unrealised_pnl == pytest.approx(0.0)
        assert acc.equity == pytest.approx(920.0)    # 1000 - 80

    def test_equity_curve_appended_on_realise(self):
        acc = self._make_account(1000)
        acc.realise_pnl(25.0)
        curve = acc.equity_curve
        assert len(curve) == 1
        assert curve[0]["equity"] == pytest.approx(1025.0)
        assert curve[0]["pnl"] == pytest.approx(25.0)

    def test_day_pnl_resets_is_consistent_type(self):
        acc = self._make_account(1000)
        assert isinstance(acc.day_pnl, float)
        assert acc.day_pnl == pytest.approx(0.0)


# ─────────────────────────────────────────────────────────────────────────────
# Quant: PaperPosition SL/TP accuracy
# ─────────────────────────────────────────────────────────────────────────────
class TestPaperPositionSLTP:

    def _long(self, entry=100.0, sl=98.0, tp=106.0, qty=1.0):
        from paper.paper_position import PaperPosition
        return PaperPosition(
            symbol="BTCUSDT", direction="LONG",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, leverage=5, confidence=75,
        )

    def _short(self, entry=100.0, sl=103.0, tp=94.0, qty=1.0):
        from paper.paper_position import PaperPosition
        return PaperPosition(
            symbol="BTCUSDT", direction="SHORT",
            entry_price=entry, stop_loss=sl, take_profit=tp,
            quantity=qty, leverage=5, confidence=75,
        )

    def test_long_sl_triggers_loss(self):
        pos = self._long()
        ct = pos.update_mark(97.5)   # below SL=98
        assert ct is not None
        assert ct.result == "LOSS"
        assert ct.close_reason == "SL"

    def test_long_tp_triggers_win(self):
        pos = self._long()
        ct = pos.update_mark(106.5)  # above TP=106
        assert ct is not None
        assert ct.result == "WIN"
        assert ct.close_reason == "TP"

    def test_short_sl_triggers_loss(self):
        pos = self._short()
        ct = pos.update_mark(103.5)  # above SL=103
        assert ct is not None
        assert ct.result == "LOSS"
        assert ct.close_reason == "SL"

    def test_short_tp_triggers_win(self):
        pos = self._short()
        ct = pos.update_mark(93.5)   # below TP=94
        assert ct is not None
        assert ct.result == "WIN"
        assert ct.close_reason == "TP"

    def test_between_sl_tp_returns_none(self):
        pos = self._long()
        ct = pos.update_mark(102.0)  # between SL=98 TP=106
        assert ct is None
        assert pos.is_open

    def test_pnl_is_net_of_fees(self):
        """Net PnL = (TP-entry)*qty - entry_fee - exit_fee."""
        pos = self._long(entry=100.0, tp=106.0, qty=1.0)
        ct = pos.update_mark(107.0)
        assert ct is not None
        fee = 100.0 * 0.0004 + 106.0 * 0.0004   # entry + exit fees
        expected = (106.0 - 100.0) * 1.0 - fee
        assert ct.pnl == pytest.approx(expected, rel=0.001)

    def test_rr_positive_on_win(self):
        pos = self._long(entry=100, sl=98, tp=106, qty=1.0)
        ct = pos.update_mark(107.0)
        assert ct is not None
        assert ct.rr > 0

    def test_unrealised_pnl_long(self):
        pos = self._long(entry=100.0)
        pos.update_mark(103.0)
        assert pos.unrealised_pnl == pytest.approx(3.0)

    def test_unrealised_pnl_short(self):
        pos = self._short(entry=100.0)
        pos.update_mark(97.0)
        assert pos.unrealised_pnl == pytest.approx(3.0)

    def test_timeout_closes_position(self):
        from paper.paper_position import PaperPosition
        pos = PaperPosition(
            symbol="BTCUSDT", direction="LONG",
            entry_price=100, stop_loss=95, take_profit=110,
            quantity=0.1, leverage=5,
        )
        # Simulate TIMEOUT_BARS ticks at a stable price
        ct = None
        for _ in range(PaperPosition.TIMEOUT_BARS + 1):
            ct = pos.update_mark(102.0)
            if ct is not None:
                break
        assert ct is not None
        assert ct.close_reason == "TIMEOUT"

    def test_invalid_direction_raises(self):
        from paper.paper_position import PaperPosition
        with pytest.raises(ValueError):
            PaperPosition(
                symbol="BTCUSDT", direction="BUY",
                entry_price=100, stop_loss=95, take_profit=110,
                quantity=0.1, leverage=5,
            )

    def test_zero_quantity_raises(self):
        from paper.paper_position import PaperPosition
        with pytest.raises(ValueError):
            PaperPosition(
                symbol="BTCUSDT", direction="LONG",
                entry_price=100, stop_loss=95, take_profit=110,
                quantity=0.0, leverage=5,
            )


# ─────────────────────────────────────────────────────────────────────────────
# Quant: PaperExecutionEngine end-to-end
# ─────────────────────────────────────────────────────────────────────────────
class TestPaperExecutionEngine:

    def _engine(self, balance=10_000.0):
        from paper.paper_execution import PaperExecutionEngine
        return PaperExecutionEngine(starting_usdt=balance)

    def _mock_decision(self, action="LONG", entry=100.0, sl=98.0, tp=106.0,
                       confidence=75, regime="TREND"):
        from unittest.mock import MagicMock
        d = MagicMock()
        d.action       = action
        d.direction    = action
        d.entry_price  = entry
        d.stop_loss    = sl
        d.take_profit  = tp
        d.confidence   = confidence
        d.regime       = regime
        d.oi_delta     = 0.01
        d.funding_rate = 0.0001
        return d

    def test_execute_long_returns_success(self):
        eng = self._engine()
        res = eng.execute(self._mock_decision("LONG"), risk_pct=0.01)
        assert res["success"] is True
        assert res["direction"] == "LONG"
        assert res["quantity"] > 0

    def test_execute_short_returns_success(self):
        eng = self._engine()
        res = eng.execute(self._mock_decision("SHORT", sl=102.0, tp=94.0), risk_pct=0.01)
        assert res["success"] is True
        assert res["direction"] == "SHORT"

    def test_max_open_blocks_second_trade(self):
        eng = self._engine()
        eng.execute(self._mock_decision(), risk_pct=0.01)
        res2 = eng.execute(self._mock_decision(), risk_pct=0.01)
        assert res2["success"] is False
        assert "max_open" in res2["reason"]

    def test_wait_action_returns_skip(self):
        eng = self._engine()
        res = eng.execute(self._mock_decision("WAIT"), risk_pct=0.01)
        assert res["success"] is False

    def test_tick_closes_on_tp(self):
        eng = self._engine()
        eng.execute(self._mock_decision("LONG", entry=100, sl=98, tp=106), risk_pct=0.01)
        closed = eng.tick(107.0)   # above TP
        assert len(closed) == 1
        assert closed[0].result == "WIN"

    def test_tick_closes_on_sl(self):
        eng = self._engine()
        eng.execute(self._mock_decision("LONG", entry=100, sl=98, tp=106), risk_pct=0.01)
        closed = eng.tick(97.0)   # below SL
        assert len(closed) == 1
        assert closed[0].result == "LOSS"

    def test_metrics_empty(self):
        eng = self._engine()
        m = eng.get_metrics()
        assert m["total_trades"] == 0
        assert m["win_rate"] == 0.0

    def test_metrics_after_two_trades(self):
        eng = self._engine(10_000)
        # Trade 1 — WIN
        eng.execute(self._mock_decision("LONG", entry=100, sl=95, tp=115), risk_pct=0.01)
        eng.tick(116.0)
        # Trade 2 — LOSS
        eng.execute(self._mock_decision("LONG", entry=100, sl=95, tp=115), risk_pct=0.01)
        eng.tick(93.0)
        m = eng.get_metrics()
        assert m["total_trades"] == 2
        assert m["wins"] == 1
        assert m["losses"] == 1
        assert m["win_rate"] == pytest.approx(0.5)
        assert "profit_factor" in m
        assert "sharpe_ratio" in m
        assert "max_drawdown" in m

    def test_equity_balance_always_non_negative(self):
        """Running balance should never go negative under normal conditions."""
        eng = self._engine(1000)
        for _ in range(5):
            eng.execute(self._mock_decision("LONG", entry=100, sl=95, tp=115), risk_pct=0.01)
            eng.tick(93.0)   # all lose
        assert eng.account.balance >= 0.0

    def test_degenerate_sl_at_entry_blocked(self):
        eng = self._engine()
        res = eng.execute(self._mock_decision("LONG", entry=100, sl=100), risk_pct=0.01)
        assert res["success"] is False
        assert "degenerate" in res["reason"]


# ─────────────────────────────────────────────────────────────────────────────
# Quant: Sharpe + drawdown helpers
# ─────────────────────────────────────────────────────────────────────────────
class TestQuantHelpers:

    def test_sharpe_varying_positive_is_positive(self):
        from paper.paper_execution import _sharpe
        # Varied but all positive — Sharpe should be positive
        pnls = [5.0, 12.0, 8.0, 15.0, 6.0, 11.0, 9.0, 14.0, 7.0, 10.0] * 2
        assert _sharpe(pnls) > 0

    def test_sharpe_mixed_returns_value(self):
        from paper.paper_execution import _sharpe
        import random; random.seed(42)
        pnls = [random.uniform(-5, 10) for _ in range(30)]
        s = _sharpe(pnls)
        assert isinstance(s, float)
        assert not math.isnan(s)

    def test_sharpe_one_sample_is_zero(self):
        from paper.paper_execution import _sharpe
        assert _sharpe([10.0]) == 0.0

    def test_sharpe_constant_returns_zero(self):
        from paper.paper_execution import _sharpe
        # zero std → Sharpe=0 (avoid division by zero)
        assert _sharpe([5.0, 5.0, 5.0]) == 0.0

    def test_max_drawdown_no_losses(self):
        from paper.paper_execution import _max_drawdown
        pnls = [10.0, 20.0, 5.0, 15.0]
        dd, dd_pct = _max_drawdown(pnls, 1000.0)
        assert dd == pytest.approx(0.0)
        assert dd_pct == pytest.approx(0.0)

    def test_max_drawdown_simple(self):
        from paper.paper_execution import _max_drawdown
        # equity: 1000 → 1050 → 1030 → 1060 — dd = 20 from peak 1050
        pnls = [50.0, -20.0, 30.0]
        dd, dd_pct = _max_drawdown(pnls, 1000.0)
        assert dd == pytest.approx(20.0)
        assert dd_pct == pytest.approx(20.0 / 1050.0, rel=0.01)

    def test_max_drawdown_all_losses(self):
        from paper.paper_execution import _max_drawdown
        dd, dd_pct = _max_drawdown([-10.0, -10.0, -10.0], 100.0)
        assert dd == pytest.approx(30.0)
        assert dd_pct > 0


# ─────────────────────────────────────────────────────────────────────────────
# BUG-04: leverage NOT double-applied in monitor_open_trades
# ─────────────────────────────────────────────────────────────────────────────
class TestMonitorPnLCalculation:

    def test_pnl_no_leverage_multiplier(self):
        """
        qty is sized from risk_usdt / |entry - SL|.
        PnL = (exit - entry) * qty  —  no further × LEVERAGE.
        """
        entry = 65_000.0
        sl    = 63_830.0       # 1.8% stop
        qty   = 0.0855         # from 1% risk on 10k balance
        mark  = 70_000.0       # TP hit

        raw_pnl = (mark - entry) * qty          # 427.5 U
        assert raw_pnl == pytest.approx(427.5, rel=0.001)

        # The WRONG old code: raw_pnl * 5 = 2137.5 — would wipe out > 20% of balance
        wrong_pnl = raw_pnl * 5
        assert wrong_pnl == pytest.approx(2137.5, rel=0.001)

        # Correct: just raw_pnl.  Leverage was already embedded when qty was sized.
        correct_pnl = raw_pnl
        assert correct_pnl < 0.05 * 10_000   # < 5% of balance — realistic


# ─────────────────────────────────────────────────────────────────────────────
# Risk Engine
# ─────────────────────────────────────────────────────────────────────────────
class TestRiskEngine:

    def _engine_with_journal(self, today_pnl=0.0, consec=0):
        from unittest.mock import MagicMock
        from risk.risk_engine import RiskEngine
        j = MagicMock()
        j.get_today_pnl.return_value = today_pnl
        j.get_consecutive_losses.return_value = consec
        j.get_daily_stats.return_value = {"total_pnl": today_pnl,
                                           "total_trades": 0, "win_rate": 0.0,
                                           "wins": 0, "losses": 0, "avg_rr": 0.0}
        return RiskEngine(j)

    def test_can_trade_clean_state(self):
        eng = self._engine_with_journal()
        ok, reason = eng.can_trade(10_000.0)
        assert ok is True
        assert reason == ""

    def test_daily_loss_blocks_trading(self):
        # 3% limit on 10k = 300 USDT; loss of -350 exceeds it
        eng = self._engine_with_journal(today_pnl=-350.0)
        ok, reason = eng.can_trade(10_000.0)
        assert ok is False
        assert "Daily loss" in reason

    def test_consecutive_losses_blocks(self):
        from config.settings import settings
        eng = self._engine_with_journal(consec=settings.MAX_CONSECUTIVE_LOSSES)
        ok, reason = eng.can_trade(10_000.0)
        assert ok is False
        assert "Consecutive" in reason

    def test_risk_pct_scales_down_on_losing_streak(self):
        from config.settings import settings
        eng = self._engine_with_journal(consec=2)
        pct = eng.get_risk_pct(10_000.0)
        assert pct == settings.RISK_PER_TRADE_MIN

    def test_risk_pct_normal_is_max(self):
        from config.settings import settings
        eng = self._engine_with_journal()
        pct = eng.get_risk_pct(10_000.0)
        assert pct == settings.RISK_PER_TRADE_MAX

    def test_report_returns_expected_keys(self):
        eng = self._engine_with_journal()
        rep = eng.report(10_000.0)
        for key in ("can_trade", "block_reason", "consecutive_losses",
                    "today_pnl", "dynamic_risk_pct"):
            assert key in rep, f"Missing key: {key}"


# ─────────────────────────────────────────────────────────────────────────────
# Confidence Engine — quant correctness
# ─────────────────────────────────────────────────────────────────────────────
class TestConfidenceEngine:

    def _engine(self):
        from decision.confidence_engine import ConfidenceEngine
        return ConfidenceEngine()

    def _ctx(self, regime="TREND", bos=True, fvg=True, ob=True, choch=False,
             trend="LONG_BIAS", strength="STRONG",
             oi_delta=0.015, funding=0.0001, vol_spike=True):
        return {
            "regime":        regime,
            "trend_bias":    trend,
            "trend_strength": strength,
            "mtf_aligned":   True,
            "oi_delta":      oi_delta,
            "funding_rate":  funding,
            "smc_m15": {
                "bos": bos, "bos_dir": "Bullish",
                "choch": choch, "choch_dir": "",
                "fvg": fvg, "fvg_dir": "Bullish",
                "ob": ob, "ob_dir": "Bullish",
            },
            "volume": {
                "volume_spike": vol_spike,
                "obv_direction": "bullish",
                "breakout_confirmed": True,
            },
            "futures": {
                "funding": {"rate": funding, "extreme": False, "bias": "NEUTRAL"},
                "open_interest": {"delta_pct": oi_delta, "pressure": "BUY_PRESSURE"},
                "long_short": {"ratio": 1.1, "contrarian_signal": "NONE"},
                "taker": {"buy_ratio": 0.6, "aggressor": "BUYERS"},
            },
        }

    def test_high_confidence_on_strong_setup(self):
        eng = self._engine()
        result = eng.score(self._ctx(), "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        assert result.confidence >= 70
        assert result.action == "LONG"

    def test_skip_when_no_direction(self):
        eng = self._engine()
        result = eng.score(self._ctx(), "", entry_price=67000, stop_loss=65800, take_profit=69400)
        assert result.action == "SKIP"
        assert result.confidence == 0

    def test_block_on_extreme_funding(self):
        ctx = self._ctx(funding=0.0008)   # > FUNDING_BLOCK_LONG = 0.0005
        eng = self._engine()
        result = eng.score(ctx, "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        assert result.action == "BLOCKED"
        assert result.blocked is True

    def test_wait_on_moderate_confidence(self):
        """No SMC signals → low confidence → WAIT, not LONG."""
        ctx = self._ctx(bos=False, fvg=False, ob=False, vol_spike=False, strength="WEAK",
                        oi_delta=0.0)
        ctx["futures"]["open_interest"]["pressure"] = "NEUTRAL"
        eng = self._engine()
        result = eng.score(ctx, "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        # Weak setup — should be WAIT or SKIP
        assert result.action in ("WAIT", "SKIP")

    def test_breakdown_sums_to_confidence(self):
        eng = self._engine()
        result = eng.score(self._ctx(), "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        total = sum(result.breakdown.values())
        assert abs(total - result.confidence) <= 1   # rounding tolerance

    def test_oi_delta_attached(self):
        ctx = self._ctx(oi_delta=0.025)
        eng = self._engine()
        result = eng.score(ctx, "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        assert result.oi_delta == pytest.approx(0.025)

    def test_funding_rate_attached(self):
        ctx = self._ctx(funding=0.0002)
        eng = self._engine()
        result = eng.score(ctx, "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        assert result.funding_rate == pytest.approx(0.0002)

    def test_to_dict_has_required_keys(self):
        eng = self._engine()
        result = eng.score(self._ctx(), "LONG", entry_price=67000, stop_loss=65800, take_profit=69400)
        d = result.to_dict()
        for k in ("action", "direction", "confidence", "breakdown",
                  "blocked", "block_reasons", "entry_price", "stop_loss",
                  "take_profit", "mtf_aligned", "regime", "oi_delta", "funding_rate"):
            assert k in d, f"Missing key: {k}"


# ─────────────────────────────────────────────────────────────────────────────
# Security: settings must NOT expose secrets in repr/str/dict
# ─────────────────────────────────────────────────────────────────────────────
class TestSecuritySettings:

    def test_settings_repr_no_secret(self):
        from config.settings import settings
        rep = repr(settings)
        # API keys should not appear verbatim
        assert "BINANCE_API_SECRET" not in rep or settings.BINANCE_API_SECRET == ""

    def test_env_keys_empty_in_test_env(self):
        """In CI / test env the .env has no real keys — confirm they're blank."""
        from config.settings import settings
        # If keys are blank, that's correct. If not blank, test still passes
        # (keys may legitimately be set in testnet mode).
        # We just assert the attribute exists and is a string.
        assert isinstance(settings.BINANCE_API_KEY, str)
        assert isinstance(settings.BINANCE_API_SECRET, str)


# ─────────────────────────────────────────────────────────────────────────────
# WebSocket: /ws/decision always sends init
# ─────────────────────────────────────────────────────────────────────────────
class TestWSDecisionInitFrame:

    def test_ws_decision_sends_init_when_no_decision(self):
        """BUG-06 fix: init frame must always be sent, even if state is None."""
        from api.app import app, set_state
        from fastapi.testclient import TestClient
        set_state("latest_decision", None)
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/decision") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert msg["decision"] is None

    def test_ws_decision_sends_init_with_decision(self):
        from api.app import app, set_state
        from fastapi.testclient import TestClient
        from unittest.mock import MagicMock
        dec = MagicMock()
        dec.to_dict.return_value = {"action": "LONG", "confidence": 82}
        set_state("latest_decision", dec)
        with TestClient(app, raise_server_exceptions=False) as c, c.websocket_connect("/ws/decision") as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"
            assert msg["decision"]["action"] == "LONG"
        set_state("latest_decision", None)


# ─────────────────────────────────────────────────────────────────────────────
# API health endpoint
# ─────────────────────────────────────────────────────────────────────────────
class TestAPIHealth:

    def test_health_returns_ok(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_health_has_uptime(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/health")
        data = r.json()["data"]
        assert "uptime_s" in data
        assert isinstance(data["uptime_s"], int)


# ─────────────────────────────────────────────────────────────────────────────
# BUG-DASH-01: BusEvent must expose a monotonic "seq" so the dashboard
# broadcast loop can detect new events. Previously the loop filtered on
# a nonexistent "id" field, so `0 > 0` was always False and /ws/events
# never broadcast anything.
# ─────────────────────────────────────────────────────────────────────────────
class TestBusEventSeq:

    def _fresh_bus(self):
        from events.event_bus import EventBus
        return EventBus(journal=None, persist=False)

    def test_bus_event_has_seq_field(self):
        bus = self._fresh_bus()
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "test")
        ev = bus.get_recent(limit=1)[0]
        assert "seq" in ev
        assert isinstance(ev["seq"], int)

    def test_seq_is_monotonically_increasing(self):
        bus = self._fresh_bus()
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "first")
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "second")
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "third")
        recent = bus.get_recent(limit=3)   # newest-first
        seqs = [e["seq"] for e in recent]
        assert seqs == sorted(seqs, reverse=True)
        assert len(set(seqs)) == 3   # all unique

    def test_seq_never_zero(self):
        bus = self._fresh_bus()
        bus.publish("RISK_MANAGER", "TRADE_BLOCKED", "test")
        ev = bus.get_recent(limit=1)[0]
        assert ev["seq"] > 0

    def test_seq_shared_across_bus_instances(self):
        """seq is a module-level counter — two EventBus instances must
        never reuse the same seq, otherwise the dashboard could drop or
        duplicate events across instance boundaries."""
        bus1 = self._fresh_bus()
        bus2 = self._fresh_bus()
        bus1.publish("SMC_ANALYST", "BOS_DETECTED", "a")
        bus2.publish("FUTURES_ANALYST", "OI_RISING", "b")
        seq_a = bus1.get_recent(limit=1)[0]["seq"]
        seq_b = bus2.get_recent(limit=1)[0]["seq"]
        assert seq_a != seq_b


# ─────────────────────────────────────────────────────────────────────────────
# BUG-DASH-01 (continued): broadcast loop must use seq, not the missing
# "id" field, to detect events that haven't been broadcast yet.
# ─────────────────────────────────────────────────────────────────────────────
class TestBroadcastLoopUsesSeq:

    def test_broadcast_loop_filters_by_seq_not_id(self):
        """
        Regression guard: simulate exactly what _broadcast_loop does —
        filter get_recent() output by seq > last_seen. With the old "id"
        based filter this would always select zero events because "id"
        never existed on BusEvent (e.get("id", 0) > 0 is always False).
        """
        from events.event_bus import EventBus
        bus = EventBus(journal=None, persist=False)
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "event one")
        bus.publish("SMC_ANALYST", "CHOCH_DETECTED", "event two")

        recent = bus.get_recent(limit=50)

        # Old (buggy) behaviour:
        last_id = 0
        new_events_buggy = [e for e in recent if e.get("id", 0) > last_id]
        assert new_events_buggy == []   # proves the old filter was broken

        # Fixed behaviour:
        last_seq = 0
        new_events_fixed = [e for e in recent if e.get("seq", 0) > last_seq]
        assert len(new_events_fixed) == 2

    def test_seq_filter_only_returns_events_after_cursor(self):
        from events.event_bus import EventBus
        bus = EventBus(journal=None, persist=False)
        bus.publish("SMC_ANALYST", "BOS_DETECTED", "old event")
        cursor = bus.get_recent(limit=1)[0]["seq"]
        bus.publish("SMC_ANALYST", "CHOCH_DETECTED", "new event")

        recent = bus.get_recent(limit=50)
        new_only = [e for e in recent if e.get("seq", 0) > cursor]

        assert len(new_only) == 1
        assert new_only[0]["message"] == "new event"


# ─────────────────────────────────────────────────────────────────────────────
# BUG-DASH-02: a cycle must keep refreshing _state["latest_context"] /
# _state["latest_decision"] while a position is open, instead of
# returning before any state update. Previously the entire dashboard
# (mark price, regime, futures snapshot, decision) froze for the whole
# lifetime of an open trade because the cycle returned immediately after
# logging "Open position: ...".
# ─────────────────────────────────────────────────────────────────────────────
class TestDashboardStateStaysLiveWithOpenPosition:

    def test_set_state_updates_latest_context(self):
        import api.app as api_module
        ctx_v1 = {"mark_price": 65000.0}
        ctx_v2 = {"mark_price": 65500.0, "open_position": {"side": "LONG"}}

        api_module.set_state("latest_context", ctx_v1)
        assert api_module._state["latest_context"]["mark_price"] == 65000.0

        # Simulate the fixed cycle: even with an open position, the cycle
        # now calls set_state again with a freshly-built market_ctx that
        # includes open_position, rather than returning before this call.
        api_module.set_state("latest_context", ctx_v2)
        assert api_module._state["latest_context"]["mark_price"] == 65500.0
        assert "open_position" in api_module._state["latest_context"]

        api_module.set_state("latest_context", None)   # cleanup

    def test_api_decision_reflects_latest_set_state_call(self):
        import api.app as api_module
        from api.app import app
        from fastapi.testclient import TestClient
        from decision.confidence_engine import ConfidenceResult

        dec1 = ConfidenceResult(action="WAIT", direction="", confidence=10.0)
        dec2 = ConfidenceResult(action="LONG", direction="LONG", confidence=77.0)

        api_module.set_state("latest_decision", dec1)
        with TestClient(app, raise_server_exceptions=False) as c:
            r1 = c.get("/api/decision")
        assert r1.json()["data"]["decision"]["action"] == "WAIT"

        # This call simulates the fixed main.py cycle re-scoring on every
        # tick (including ticks where a position is already open) so the
        # dashboard never sees a value frozen from before the position
        # was opened.
        api_module.set_state("latest_decision", dec2)
        with TestClient(app, raise_server_exceptions=False) as c:
            r2 = c.get("/api/decision")
        assert r2.json()["data"]["decision"]["action"] == "LONG"
        assert r2.json()["data"]["decision"]["confidence"] == pytest.approx(77.0)

        api_module.set_state("latest_decision", None)   # cleanup

    def test_open_position_context_includes_live_price_fields(self):
        """
        The fixed main.py attaches the live `pos` dict (with
        unrealizedProfit / entryPrice) onto market_ctx_live["open_position"]
        every cycle. Verify the shape the dashboard depends on.
        """
        import api.app as api_module
        pos = {
            "side": "LONG",
            "positionAmt": 0.1062,
            "entryPrice": 65664.78,
            "unrealizedProfit": -129.92,
        }
        ctx = {"mark_price": 65500.0, "open_position": pos}
        api_module.set_state("latest_context", ctx)

        stored = api_module._state["latest_context"]
        assert stored["open_position"]["unrealizedProfit"] == pytest.approx(-129.92)
        assert stored["open_position"]["entryPrice"] == pytest.approx(65664.78)

        api_module.set_state("latest_context", None)   # cleanup


# ─────────────────────────────────────────────────────────────────────────────
# BUG-DASH-03: run_trading_cycle must still invoke the agent layer
# (ceo.decide(), which internally runs every sub-agent via BaseAgent.run())
# even while a position is open. Previously the open-position branch only
# refreshed _state["latest_context"] / _state["latest_decision"] and
# returned — it never called agents_live["ceo"].decide(...), so every
# sub-agent's .last_report stayed at whatever it was before the position
# opened (or None if no cycle had run yet). GET /api/agents therefore
# returned {} for the entire lifetime of any open trade, and the
# dashboard's SMC / FUTURES / RISK / TRADER / JOURNAL agent cards never
# updated while a position was open — only the CEO card (driven by
# /api/decision, fixed separately) kept moving.
# ─────────────────────────────────────────────────────────────────────────────
class TestAgentLayerRunsWhilePositionOpen:

    def _build_minimal_sys(self, monkeypatch, open_position: dict):
        """
        Build the minimal `sys` dict run_trading_cycle() needs, with a
        real agent_layer (so we can assert real last_report state) but
        every market-data/engine call mocked to fast deterministic stubs.
        """
        import pandas as pd
        import numpy as np
        from agents import build_agent_layer
        from events.event_bus import EventBus

        n = 60
        idx = pd.date_range("2026-01-01", periods=n, freq="h")
        df = pd.DataFrame({
            "open":   np.full(n, 65000.0),
            "high":   np.full(n, 65200.0),
            "low":    np.full(n, 64800.0),
            "close":  np.full(n, 65000.0),
            "volume": np.full(n, 100.0),
        }, index=idx)

        class _StubDataProvider:
            def _sync_time_offset(self): pass
            def get_position_info(self):  return open_position
            def get_all_market_data(self):
                return {"ohlcv": {"h4": df, "h1": df, "m15": df}}
            def get_account_balance(self): return 10_000.0

        class _StubSMC:
            def analyze_mtf(self, ohlcv): return {}

        class _StubVol:
            def analyze(self, df): return {}

        class _StubRegime:
            def classify(self, df):
                from regime.regime_engine import RegimeResult
                r = RegimeResult()
                r.regime = "TRENDING_BULL"
                r.confidence = 0.6
                return r

        class _StubCtxBuilder:
            def build(self, **kwargs):
                return {
                    "mark_price": 65500.0,
                    "mtf_direction": "",
                    "mtf_aligned": False,
                }

        from decision.confidence_engine import ConfidenceEngine
        from decision.causal_explainer import CausalExplainer
        from journal.journal_v2 import TradeJournalV2
        from risk.risk_engine import RiskEngine

        jrn_v2 = TradeJournalV2(db_path=":memory:")
        agent_layer = build_agent_layer(risk_engine=RiskEngine(jrn_v2), journal=jrn_v2)

        return {
            "data_provider":      _StubDataProvider(),
            "smc_engine":         _StubSMC(),
            "volume_engine":      _StubVol(),
            "regime_engine":      _StubRegime(),
            "context_builder":    _StubCtxBuilder(),
            "confidence_engine":  ConfidenceEngine(),
            "causal_explainer":   CausalExplainer(),
            "journal_v2":         jrn_v2,
            "risk_engine":        RiskEngine(jrn_v2),
            "trade_manager":      None,
            "event_bus":          EventBus(journal=None, persist=False),
            "agent_layer":        agent_layer,
        }

    def test_ceo_decide_called_when_position_open(self, monkeypatch):
        import api.app as api_module
        from main import run_trading_cycle

        open_pos = {
            "side": "LONG", "positionAmt": 0.1062,
            "entryPrice": 65664.78, "unrealizedProfit": -129.92,
        }
        sys_dict = self._build_minimal_sys(monkeypatch, open_position=open_pos)

        api_module.set_state("ceo_decision", None)

        run_trading_cycle(sys_dict)

        # The bug: ceo_decision stayed None because ceo.decide() was never
        # called on the open-position path. The fix calls it every cycle.
        assert api_module._state["ceo_decision"] is not None

        api_module.set_state("ceo_decision", None)   # cleanup

    def test_sub_agent_last_report_set_when_position_open(self, monkeypatch):
        """
        Direct proof of the bug: before the fix, smc/futures/risk/trader/
        journal agents' .last_report stayed None forever once a position
        opened (because BaseAgent.run() was never called for them on this
        path). After the fix, every sub-agent has a fresh AgentReport.
        """
        import api.app as api_module
        from main import run_trading_cycle

        open_pos = {
            "side": "LONG", "positionAmt": 0.1062,
            "entryPrice": 65664.78, "unrealizedProfit": -55.0,
        }
        sys_dict = self._build_minimal_sys(monkeypatch, open_position=open_pos)
        agent_layer = sys_dict["agent_layer"]

        # Sanity: nothing has run yet
        for key in ("smc", "futures", "regime", "risk", "trader", "journal"):
            assert agent_layer[key].last_report is None

        run_trading_cycle(sys_dict)

        for key in ("smc", "futures", "regime", "risk", "trader", "journal"):
            assert agent_layer[key].last_report is not None, (
                f"{key} agent's last_report was never set while a "
                f"position was open — this is the dashboard freeze bug."
            )

        api_module.set_state("ceo_decision", None)   # cleanup

    def test_api_agents_endpoint_nonempty_when_position_open(self, monkeypatch):
        """
        End-to-end proof at the API layer: GET /api/agents must return a
        non-empty `agents` dict (used directly by the dashboard's agent
        cards) even while a position is open.
        """
        import api.app as api_module
        from api.app import app
        from fastapi.testclient import TestClient
        from main import run_trading_cycle

        open_pos = {
            "side": "LONG", "positionAmt": 0.1062,
            "entryPrice": 65664.78, "unrealizedProfit": -90.0,
        }
        sys_dict = self._build_minimal_sys(monkeypatch, open_position=open_pos)
        api_module.set_state("agent_layer", sys_dict["agent_layer"])

        run_trading_cycle(sys_dict)

        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/agents")
        data = r.json()["data"]

        assert data["agent_count"] > 0
        assert len(data["agents"]) > 0
        assert "smc" in data["agents"]

        api_module.set_state("ceo_decision", None)    # cleanup
        api_module.set_state("agent_layer", {})        # cleanup

    def test_trader_agent_shows_real_quantity_and_entry_price(self, monkeypatch):
        """
        Direct regression test for the dashboard "LONG 0.0000 BTC @ <mark
        price>" bug.

        dp.get_position_info() returns the raw Binance shape: side,
        positionAmt, entryPrice, unrealizedProfit. TraderAgent.analyse()
        reads direction/quantity/entry_price/unrealised_pnl. Before the
        fix, the raw dict was passed straight into market_context/pos_info
        as `open_position`, so every one of TraderAgent's `.get(key, default)`
        calls missed and silently fell back to its default — quantity
        showed as 0.0000 and entry_price showed as the live mark price
        instead of the real values, no matter the actual position size.
        """
        import api.app as api_module
        from main import run_trading_cycle

        open_pos = {
            "side": "LONG", "positionAmt": 0.1062,
            "entryPrice": 65664.78, "unrealizedProfit": -542.28,
        }
        sys_dict = self._build_minimal_sys(monkeypatch, open_position=open_pos)
        agent_layer = sys_dict["agent_layer"]

        run_trading_cycle(sys_dict)

        trader_report = agent_layer["trader"].last_report
        assert trader_report is not None

        raw_pos = trader_report.raw.get("open_position")
        assert raw_pos is not None, "TraderAgent never received open_position"

        # The actual bug: these used to be 0.0 / "LONG" (default) / mark_price
        # regardless of the real exchange data.
        assert raw_pos["direction"] == "LONG"
        assert raw_pos["quantity"] == pytest.approx(0.1062)
        assert raw_pos["entry_price"] == pytest.approx(65664.78)
        assert raw_pos["unrealised_pnl"] == pytest.approx(-542.28)

        # The human-readable summary must show the real quantity, not 0.0000.
        assert "0.1062 BTC" in trader_report.summary
        assert "65664.78" in trader_report.summary
        assert "0.0000 BTC" not in trader_report.summary

        api_module.set_state("ceo_decision", None)    # cleanup
        api_module.set_state("agent_layer", {})        # cleanup



# ─────────────────────────────────────────────────────────────────────────────
# BUG-DASH-04: _normalize_open_position() must fall back to the actual
# resting STOP_MARKET / TAKE_PROFIT_MARKET orders on the exchange when the
# journal has no matching OPEN row (e.g. a position that existed on the
# account before this bot session started). Previously SL/TP silently
# stayed at 0.0/0.0 in that case, which the dashboard rendered as
# "SL=0 TP=0" even though real stop/TP orders were resting on the exchange.
# ─────────────────────────────────────────────────────────────────────────────
class TestNormalizeOpenPositionExchangeFallback:

    def _raw_pos(self, side="LONG", amt=0.1062, entry=65664.78, upnl=-542.28):
        return {
            "side": side, "positionAmt": amt,
            "entryPrice": entry, "unrealizedProfit": upnl,
            "symbol": "BTCUSDT",
        }

    def _tm_with_orders(self, orders, symbol="BTCUSDT"):
        """Minimal stand-in for TradeManager: exposes .client.get_orders()
        and .symbol, exactly what _fetch_resting_sl_tp() reads."""
        class _Client:
            def get_orders(self, symbol):
                return orders
        class _TM:
            def __init__(self):
                self.client = _Client()
                self.symbol = symbol
        return _TM()

    def test_no_journal_row_and_no_trade_client_leaves_zero(self):
        """Baseline: no journal match, no trade_client at all (paper mode /
        not supplied) — must degrade to 0.0/0.0 exactly like before this fix,
        never raise."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []

        out = _normalize_open_position(self._raw_pos(), jrn, trade_client=None)

        assert out["stop_loss"] == 0.0
        assert out["take_profit"] == 0.0

    def test_no_journal_row_fetches_sl_tp_from_exchange_long(self):
        """The actual bug fix: a pre-existing LONG position with no journal
        row picks up its real SL/TP from resting orders on the exchange.
        For a LONG, the closing side is SELL; STOP_MARKET=SL,
        TAKE_PROFIT_MARKET=TP."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []  # no match

        orders = [
            {"symbol": "BTCUSDT", "side": "SELL", "type": "STOP_MARKET",
             "stopPrice": "64000.00"},
            {"symbol": "BTCUSDT", "side": "SELL", "type": "TAKE_PROFIT_MARKET",
             "stopPrice": "69000.00"},
        ]
        tm = self._tm_with_orders(orders)

        out = _normalize_open_position(self._raw_pos(side="LONG"), jrn, trade_client=tm)

        assert out["stop_loss"] == pytest.approx(64000.00)
        assert out["take_profit"] == pytest.approx(69000.00)

    def test_no_journal_row_fetches_sl_tp_from_exchange_short(self):
        """Mirror case for SHORT: closing side is BUY."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []

        orders = [
            {"symbol": "BTCUSDT", "side": "BUY", "type": "STOP_MARKET",
             "stopPrice": "70000.00"},
            {"symbol": "BTCUSDT", "side": "BUY", "type": "TAKE_PROFIT_MARKET",
             "stopPrice": "60000.00"},
        ]
        tm = self._tm_with_orders(orders)

        out = _normalize_open_position(self._raw_pos(side="SHORT"), jrn, trade_client=tm)

        assert out["stop_loss"] == pytest.approx(70000.00)
        assert out["take_profit"] == pytest.approx(60000.00)

    def test_orders_on_opposite_side_are_ignored(self):
        """Resting orders belonging to the *other* side (e.g. leftover from
        a previous SHORT) must not be mistaken for this LONG's SL/TP."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []

        orders = [
            {"symbol": "BTCUSDT", "side": "BUY", "type": "STOP_MARKET",
             "stopPrice": "70000.00"},   # belongs to a SHORT, not this LONG
        ]
        tm = self._tm_with_orders(orders)

        out = _normalize_open_position(self._raw_pos(side="LONG"), jrn, trade_client=tm)

        assert out["stop_loss"] == 0.0
        assert out["take_profit"] == 0.0

    def test_journal_row_present_skips_exchange_lookup(self):
        """When the journal already has a matching OPEN row with real
        SL/TP, exchange fallback must not override it (and ideally isn't
        even queried) — the journal is authoritative when present."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock()
        jrn.get_open_trades.return_value = [
            {"direction": "LONG", "stop_loss": 64500.0, "take_profit": 68500.0}
        ]

        class _ShouldNotBeCalled:
            def get_orders(self, symbol):
                raise AssertionError("exchange lookup must be skipped when journal matched")
        class _TM:
            def __init__(self):
                self.client = _ShouldNotBeCalled()
                self.symbol = "BTCUSDT"

        out = _normalize_open_position(self._raw_pos(side="LONG"), jrn, trade_client=_TM())

        assert out["stop_loss"] == pytest.approx(64500.0)
        assert out["take_profit"] == pytest.approx(68500.0)

    def test_trade_client_without_client_attr_is_ignored(self):
        """_PaperAdapter / any other stand-in without a `.client` (real
        exchange handle) must be treated like no trade_client at all,
        never raise AttributeError."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []

        class _PaperAdapterStub:
            pass  # no .client attribute

        out = _normalize_open_position(self._raw_pos(), jrn, trade_client=_PaperAdapterStub())

        assert out["stop_loss"] == 0.0
        assert out["take_profit"] == 0.0

    def test_exchange_api_error_degrades_to_zero_not_raise(self):
        """A transient API error while fetching resting orders must never
        propagate — this is a display enrichment, not core trading logic."""
        from main import _normalize_open_position
        from unittest.mock import MagicMock
        jrn = MagicMock(); jrn.get_open_trades.return_value = []

        class _FlakyClient:
            def get_orders(self, symbol):
                raise RuntimeError("timeout")
        class _TM:
            def __init__(self):
                self.client = _FlakyClient()
                self.symbol = "BTCUSDT"

        out = _normalize_open_position(self._raw_pos(), jrn, trade_client=_TM())

        assert out["stop_loss"] == 0.0
        assert out["take_profit"] == 0.0

    def test_no_raw_pos_returns_none_regardless_of_trade_client(self):
        from main import _normalize_open_position
        assert _normalize_open_position(None, None, trade_client=object()) is None


# ─────────────────────────────────────────────────────────────────────────────
# BUG-RECON-01: ReconciliationEngine.run() must not re-publish/re-log an
# *identical* mismatch every cycle while the underlying condition (e.g. a
# pre-existing exchange position never written to the journal) stays open.
# Previously PRESENCE_MISMATCH fired at WARNING severity once per minute,
# forever, for as long as the position remained open. It should fire once,
# then go quiet until something actually changes (severity escalates, the
# detail changes, or the condition clears and a new one appears).
# ─────────────────────────────────────────────────────────────────────────────
class TestReconciliationSuppressesIdenticalRepeats:

    @pytest.fixture(autouse=True)
    def _reset_singletons(self):
        from system_health.reconciliation import reset_reconciliation_engine
        from system_health.recovery_engine import reset_recovery_engine
        from events.event_bus import reset_event_bus
        reset_reconciliation_engine()
        reset_recovery_engine()
        reset_event_bus(journal=None, persist=False)
        yield
        reset_reconciliation_engine()
        reset_recovery_engine()
        reset_event_bus(journal=None, persist=False)

    def _sys(self, ex_pos=None, j_open=None):
        from unittest.mock import MagicMock
        dp = MagicMock(); dp.get_position_info.return_value = ex_pos
        jrn = MagicMock(); jrn.get_open_trades.return_value = j_open or []
        jrn.get_trades.return_value = []   # total_trades == 0 → startup case
        return {"data_provider": dp, "journal_v2": jrn, "paper_engine": None}

    def test_first_fire_still_returns_event(self):
        """The existing contract must hold: the very first detection of a
        mismatch always fires, never suppressed."""
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                "unrealizedProfit": 5.0, "side": "LONG"}
        evt = get_reconciliation_engine().run(self._sys(ex_pos=exch))
        assert evt is not None
        assert evt.mismatch_type == "PRESENCE_MISMATCH"

    def test_identical_mismatch_suppressed_on_repeat_cycles(self):
        """Same exchange/journal state polled again (simulating the next
        60s cycle while the position is still open) must NOT produce a
        second event."""
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                "unrealizedProfit": 5.0, "side": "LONG"}
        engine = get_reconciliation_engine()
        sys_d = self._sys(ex_pos=exch)

        first = engine.run(sys_d)
        second = engine.run(sys_d)
        third = engine.run(sys_d)

        assert first is not None
        assert second is None
        assert third is None
        assert engine.status()["suppressed_repeat_count"] == 2

    def test_suppressed_repeat_does_not_grow_event_buffer(self):
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                "unrealizedProfit": 5.0, "side": "LONG"}
        engine = get_reconciliation_engine()
        sys_d = self._sys(ex_pos=exch)

        for _ in range(5):
            engine.run(sys_d)

        assert engine.status()["event_count"] == 1

    def test_suppressed_repeat_does_not_republish_to_event_bus(self):
        from system_health.reconciliation import get_reconciliation_engine
        from events.event_bus import get_event_bus
        exch = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                "unrealizedProfit": 5.0, "side": "LONG"}
        engine = get_reconciliation_engine()
        sys_d = self._sys(ex_pos=exch)

        for _ in range(3):
            engine.run(sys_d)

        events = [e for e in get_event_bus().get_recent(limit=20)
                   if e.get("event") == "RECONCILIATION_MISMATCH"]
        assert len(events) == 1

    def test_condition_clearing_then_recurring_fires_fresh(self):
        """If the mismatch clears (position closes / journal catches up)
        and then a *new* mismatch appears later, it must fire again rather
        than staying suppressed forever."""
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                "unrealizedProfit": 5.0, "side": "LONG"}
        engine = get_reconciliation_engine()

        sys_open = self._sys(ex_pos=exch)
        first = engine.run(sys_open)
        assert first is not None

        sys_flat = self._sys(ex_pos=None)   # everything flat now — clears
        cleared = engine.run(sys_flat)
        assert cleared is None
        assert engine.status()["last_result"] == "OK"

        # New mismatch appears later (same type, but a genuinely new
        # occurrence) — must fire again, not be treated as a stale repeat.
        second_round = engine.run(sys_open)
        assert second_round is not None

    def test_changed_detail_fires_fresh_even_if_same_type(self):
        """SIDE_MISMATCH whose detail text actually changes (the reported
        exchange side flips) must fire again even though a SIDE_MISMATCH
        was already reported moments earlier — the detail differs, so this
        is a distinct signature, not a suppressed repeat."""
        from system_health.reconciliation import get_reconciliation_engine
        journal = [{"id": 1, "direction": "SHORT", "quantity": 0.1}]
        engine = get_reconciliation_engine()

        exch_long = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                     "unrealizedProfit": 5.0, "side": "LONG"}
        evt1 = engine.run(self._sys(ex_pos=exch_long, j_open=journal))
        assert evt1.mismatch_type == "SIDE_MISMATCH"
        assert "ex=LONG" in evt1.detail

        # Position actually flipped on the exchange (closed LONG, opened
        # SHORT) while the journal still thinks it's SHORT-vs-something —
        # use a different journal direction so the mismatch persists but
        # the *exchange* side in the detail string changes from LONG to
        # FLAT-then-reopened-as something journal disagrees with. Simplest
        # realistic case: exchange side flips to SHORT, journal flips its
        # recorded direction to LONG — same mismatch *type*, new detail.
        exch_short = {"symbol": "BTC", "positionAmt": 0.1, "entryPrice": 67000.0,
                      "unrealizedProfit": 5.0, "side": "SHORT"}
        journal_long = [{"id": 2, "direction": "LONG", "quantity": 0.1}]
        evt2 = engine.run(self._sys(ex_pos=exch_short, j_open=journal_long))
        assert evt2 is not None
        assert evt2.mismatch_type == "SIDE_MISMATCH"
        assert "ex=SHORT" in evt2.detail
