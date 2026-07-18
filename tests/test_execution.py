"""Unit tests for Execution, Risk, and Analytics layers."""
import pytest
import os
import tempfile
import numpy as np
import pandas as pd
from unittest.mock import MagicMock, patch, PropertyMock

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# TradeManager
# ─────────────────────────────────────────────────────────────────────────────

class TestTradeManager:

    def _make_manager(self):
        """Build a TradeManager with a fully mocked client."""
        from execution.trade_manager import TradeManager

        mock_client = MagicMock()
        mock_client.exchange_info.return_value = {
            "symbols": [{
                "symbol": "BTCUSDT",
                "filters": [
                    {"filterType": "LOT_SIZE",     "stepSize": "0.001", "minQty": "0.001", "maxQty": "100.0"},
                    {"filterType": "PRICE_FILTER",  "tickSize": "0.10"},
                ],
            }]
        }
        mock_provider      = MagicMock()
        mock_provider.client = mock_client

        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL              = "BTCUSDT"
            ms.LEVERAGE            = 5
            ms.RISK_PER_TRADE_MAX  = 0.01
            ms.RISK_PER_TRADE_MIN  = 0.005
            manager = TradeManager(mock_provider)

        manager.client = mock_client   # re-attach after patch exits
        return manager, mock_client

    def test_import(self):
        from execution.trade_manager import TradeManager
        assert TradeManager is not None

    def test_round_qty_floor(self):
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        # 0.1234 → floor to 0.001 step → 0.123
        qty = m._round_qty(0.1234)
        assert abs(qty - 0.123) < 1e-9

    def test_round_qty_min(self):
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        qty = m._round_qty(0.0001)
        assert qty == 0.001  # never below minQty

    def test_position_size_calculation(self):
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        # risk = 1000 * 0.01 = 10 USDT
        # sl_dist = 50_500 - 50_000 = 500
        # raw qty = 10/500 = 0.02 BTC
        # margin cap: 20% of 1000 = 200 U margin → notional = 200*5 = 1000 U
        # max qty by cap = 1000/50_500 ≈ 0.0198 → rounds to 0.019 (step 0.001)
        qty = m.calculate_position_size(
            balance=1_000.0,
            entry_price=50_500.0,
            stop_loss=50_000.0,
            risk_pct=0.01,
        )
        assert qty == pytest.approx(0.019, abs=1e-6)

    def test_position_size_no_cap_when_small(self):
        """When risk-based qty is under the margin cap, it should not be reduced."""
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        # risk = 5000 * 0.01 = 50 USDT, sl_dist = 5000
        # raw qty = 50/5000 = 0.01 BTC
        # margin cap: 20% of 5000 = 1000 U → notional 5000 U → max 5000/50_000 = 0.1 BTC
        # 0.01 < 0.1 → no cap applied
        qty = m.calculate_position_size(
            balance=5_000.0,
            entry_price=50_000.0,
            stop_loss=45_000.0,
            risk_pct=0.01,
        )
        assert qty == pytest.approx(0.01, abs=1e-6)

    def test_position_size_zero_sl_distance(self):
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        qty = m.calculate_position_size(1_000.0, 50_000.0, 50_000.0)
        assert qty == 0.001  # minimum

    def test_place_market_order_buy(self):
        from execution.trade_manager import TradeManager
        m, client = self._make_manager()
        client.new_order.return_value = {"orderId": 123, "status": "FILLED"}
        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            m.symbol  = "BTCUSDT"
            result    = m.place_market_order("LONG", 0.05)
        client.new_order.assert_called_once()
        call_kwargs = client.new_order.call_args[1]
        assert call_kwargs["side"] == "BUY"
        assert call_kwargs["type"] == "MARKET"

    def test_place_market_order_sell(self):
        from execution.trade_manager import TradeManager
        m, client = self._make_manager()
        client.new_order.return_value = {"orderId": 456, "status": "FILLED"}
        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            m.symbol  = "BTCUSDT"
            result    = m.place_market_order("SHORT", 0.05)
        call_kwargs = client.new_order.call_args[1]
        assert call_kwargs["side"] == "SELL"

    def test_round_price_precision(self):
        from execution.trade_manager import TradeManager
        m, _ = self._make_manager()
        price_str = m._round_price(50_123.456)
        # tickSize=0.10 → 1 decimal
        assert "." in price_str
        decimals = len(price_str.split(".")[1])
        assert decimals <= 2


# ─────────────────────────────────────────────────────────────────────────────
# TradeManager — circuit breaker wiring (v16 P0-B)
# ─────────────────────────────────────────────────────────────────────────────

class TestTradeManagerCircuitBreaker:
    """execution/trade_manager.py order-placement calls now share the same
    'binance_trade' CircuitBreaker data/binance_provider.py already uses
    for trade/account reads (audit finding #8 / P1 item 6)."""

    def _make_manager(self):
        return TestTradeManager()._make_manager()

    @pytest.fixture(autouse=True)
    def _reset_trade_breaker(self):
        """The 'binance_trade' breaker is a process-wide singleton shared
        with data/binance_provider.py — force it CLOSED before and after
        each test in this class so these tests can't leak state into any
        other test that happens to run in the same session."""
        from execution.trade_manager import _TRADE_BREAKER
        _TRADE_BREAKER.reset()
        yield
        _TRADE_BREAKER.reset()

    def test_shares_same_breaker_instance_as_binance_provider(self):
        """Same named breaker, not a duplicate — get_breaker() is a
        thread-safe singleton registry keyed by name."""
        from execution.trade_manager import _TRADE_BREAKER as tm_breaker
        from data.binance_provider import _TRADE_BREAKER as dp_breaker
        assert tm_breaker is dp_breaker
        assert tm_breaker.name == "binance_trade"

    def test_open_breaker_fast_fails_without_calling_client(self):
        """When the breaker is OPEN, place_market_order must raise
        CircuitBreakerOpen immediately and must NOT call the exchange
        client at all — that's the entire point of a fast-fail breaker."""
        from system_health.circuit_breaker import CircuitBreakerOpen
        from execution.trade_manager import _TRADE_BREAKER

        m, client = self._make_manager()
        # Force OPEN the same way CircuitBreaker itself would after
        # failure_threshold consecutive failures (mirrors the pattern
        # already used in tests/test_v15_production.py::TestCircuitBreaker).
        for _ in range(_TRADE_BREAKER._failure_threshold):
            _TRADE_BREAKER._on_failure("synthetic test failure")
        assert _TRADE_BREAKER.is_open

        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            m.symbol  = "BTCUSDT"
            with pytest.raises(CircuitBreakerOpen):
                m.place_market_order("LONG", 0.01)

        client.new_order.assert_not_called()

    def test_closed_breaker_allows_normal_order_placement(self):
        """Sanity check: with the breaker CLOSED (default), order
        placement is unaffected — same behavior as before this fix."""
        from execution.trade_manager import _TRADE_BREAKER
        assert not _TRADE_BREAKER.is_open

        m, client = self._make_manager()
        client.new_order.return_value = {"orderId": 789, "status": "FILLED"}
        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            m.symbol  = "BTCUSDT"
            result = m.place_market_order("LONG", 0.01)
        assert result["orderId"] == 789
        client.new_order.assert_called_once()

    def test_tier_fallback_success_counts_as_one_breaker_success(self):
        """place_stop_loss's internal tier-1→tier-2 fallback (e.g. a -4120
        'unsupported' response) is normal negotiation, handled inside the
        function — it must NOT be recorded as a breaker failure. Only a
        genuinely unhandled/retryable error escaping the whole function
        should count."""
        from binance.error import ClientError
        from execution.trade_manager import _TRADE_BREAKER

        m, client = self._make_manager()
        tier1_error = ClientError(400, -4120, "unsupported", {})
        client.new_order.side_effect = [
            tier1_error,
            {"orderId": 111, "status": "NEW"},  # tier 2 succeeds
        ]
        with patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            m.symbol  = "BTCUSDT"
            result = m.place_stop_loss("LONG", 0.01, 49000.0)

        assert result["orderId"] == 111
        assert not _TRADE_BREAKER.is_open
        assert _TRADE_BREAKER._failure_count == 0


# ─────────────────────────────────────────────────────────────────────────────
# RiskEngine
# ─────────────────────────────────────────────────────────────────────────────

class TestRiskEngine:

    def _make_journal(self, pnl=0.0, streak=0, trades=0, win_rate=0.0):
        j = MagicMock()
        j.get_today_pnl.return_value            = pnl
        j.get_consecutive_losses.return_value   = streak
        j.get_daily_stats.return_value          = {
            "total_pnl":    pnl,
            "total_trades": trades,
            "win_rate":     win_rate,
        }
        return j

    def test_import(self):
        from risk.risk_engine import RiskEngine
        assert RiskEngine is not None

    def test_can_trade_normal(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            eng = RiskEngine(self._make_journal(pnl=0.0, streak=0))
            ok, reason = eng.can_trade(1_000.0)
        assert ok is True
        assert reason == ""

    def test_daily_loss_blocks_trading(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            # daily loss = -40 U > limit 30 U
            eng = RiskEngine(self._make_journal(pnl=-40.0))
            ok, reason = eng.can_trade(1_000.0)
        assert ok is False
        assert "loss" in reason.lower()

    def test_consecutive_losses_blocks_trading(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            eng = RiskEngine(self._make_journal(streak=3))
            ok, reason = eng.can_trade(1_000.0)
        assert ok is False

    def test_dynamic_risk_reduces_on_streak(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            eng_clean  = RiskEngine(self._make_journal(streak=0))
            eng_streak = RiskEngine(self._make_journal(streak=2))
            r_clean    = eng_clean.get_risk_pct(1_000.0)
            r_streak   = eng_streak.get_risk_pct(1_000.0)
        assert r_streak <= r_clean

    def test_disable_then_can_trade_returns_false(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            eng = RiskEngine(self._make_journal())
            eng.disable_trading_today("unit test")
            ok, _ = eng.can_trade(1_000.0)
        assert ok is False

    def test_report_contains_required_keys(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            ms.MAX_DAILY_LOSS          = 0.03
            ms.MAX_CONSECUTIVE_LOSSES  = 3
            ms.RISK_PER_TRADE_MIN      = 0.005
            ms.RISK_PER_TRADE_MAX      = 0.01
            # P1-B1: report() now also calls get_leverage()/_volatility_factor(),
            # which read LEVERAGE and VOLATILITY_RISK_THRESHOLD/FLOOR — without
            # these, the auto-generated MagicMock attributes aren't usable in
            # arithmetic/comparisons and report() raises before returning.
            ms.LEVERAGE                 = 5
            ms.VOLATILITY_RISK_THRESHOLD = 0.015
            ms.VOLATILITY_RISK_FLOOR    = 0.5
            eng = RiskEngine(self._make_journal())
            rpt = eng.report(1_000.0)
        for key in ("can_trade", "block_reason", "consecutive_losses",
                    "today_pnl", "dynamic_risk_pct"):
            assert key in rpt


# ─────────────────────────────────────────────────────────────────────────────
# TradeJournal
# ─────────────────────────────────────────────────────────────────────────────

class TestTradeJournal:

    @pytest.fixture
    def tmp_journal(self, tmp_path):
        """Return a fresh TradeJournal backed by a temp SQLite file."""
        db = str(tmp_path / "test_journal.db")
        with patch("analytics.trade_journal.settings") as ms:
            ms.JOURNAL_DB_PATH = db
            ms.SYMBOL          = "BTCUSDT"
            from analytics.trade_journal import TradeJournal
            j = TradeJournal(db_path=db)
        return j

    def _make_record(self, direction="LONG", result="OPEN", pnl=0.0):
        from analytics.trade_journal import TradeRecord
        from datetime import datetime, timezone
        r = TradeRecord()
        r.timestamp   = datetime.now(timezone.utc).isoformat()
        r.symbol      = "BTCUSDT"
        r.direction   = direction
        r.regime      = "TREND"
        r.bos         = 1
        r.fvg         = 1
        r.entry_price = 50_000.0
        r.stop_loss   = 49_500.0
        r.take_profit = 51_000.0
        r.confidence  = 77.78
        r.score       = 7
        r.result      = result
        r.pnl         = pnl
        return r

    def test_import(self):
        from analytics.trade_journal import TradeJournal, TradeRecord
        assert TradeJournal is not None
        assert TradeRecord  is not None

    def test_save_returns_positive_id(self, tmp_journal):
        tid = tmp_journal.save_trade(self._make_record())
        assert tid >= 1

    def test_save_multiple_ids_increment(self, tmp_journal):
        t1 = tmp_journal.save_trade(self._make_record())
        t2 = tmp_journal.save_trade(self._make_record())
        assert t2 > t1

    def test_get_open_trades(self, tmp_journal):
        tmp_journal.save_trade(self._make_record(result="OPEN"))
        open_trades = tmp_journal.get_open_trades()
        assert len(open_trades) >= 1
        assert open_trades[0]["result"] == "OPEN"

    def test_update_result_win(self, tmp_journal):
        tid = tmp_journal.save_trade(self._make_record())
        ok  = tmp_journal.update_trade_result(tid, "WIN", 51_000.0, 50.0)
        assert ok is True

    def test_rr_computed_on_update(self, tmp_journal):
        rec           = self._make_record()
        rec.entry_price = 50_000.0
        rec.stop_loss   = 49_000.0   # risk = 1000
        rec.take_profit = 52_000.0
        tid = tmp_journal.save_trade(rec)
        tmp_journal.update_trade_result(tid, "WIN", 52_000.0, 100.0)

        import sqlite3
        with sqlite3.connect(tmp_journal.db_path) as c:
            c.row_factory = sqlite3.Row
            row = c.execute("SELECT rr FROM trades WHERE id=?", (tid,)).fetchone()
        # (52000 - 50000) / (50000 - 49000) = 2.0
        assert abs(row["rr"] - 2.0) < 0.01

    def test_consecutive_losses_zero_initially(self, tmp_journal):
        assert tmp_journal.get_consecutive_losses() == 0

    def test_consecutive_losses_counts(self, tmp_journal):
        for _ in range(3):
            tid = tmp_journal.save_trade(self._make_record())
            tmp_journal.update_trade_result(tid, "LOSS", 49_500.0, -50.0)
        assert tmp_journal.get_consecutive_losses() == 3

    def test_streak_resets_on_win(self, tmp_journal):
        for _ in range(2):
            tid = tmp_journal.save_trade(self._make_record())
            tmp_journal.update_trade_result(tid, "LOSS", 49_500.0, -50.0)
        tid = tmp_journal.save_trade(self._make_record())
        tmp_journal.update_trade_result(tid, "WIN", 51_000.0, 50.0)
        assert tmp_journal.get_consecutive_losses() == 0

    def test_performance_summary_keys(self, tmp_journal):
        tid = tmp_journal.save_trade(self._make_record())
        tmp_journal.update_trade_result(tid, "WIN", 51_000.0, 50.0)
        s   = tmp_journal.get_performance_summary()
        for key in ("total_trades", "wins", "losses", "win_rate",
                    "total_pnl", "avg_rr", "profit_factor"):
            assert key in s

    def test_daily_stats_no_trades(self, tmp_journal):
        s = tmp_journal.get_daily_stats("2099-12-31")
        assert s["total_trades"] == 0
        assert s["win_rate"]     == 0.0

    def test_today_pnl_is_float(self, tmp_journal):
        pnl = tmp_journal.get_today_pnl()
        assert isinstance(pnl, float)

    def test_from_decision_classmethod(self):
        from analytics.trade_journal import TradeRecord
        from features.smc_engine  import SMCSignals
        from features.volume_engine import VolumeSignals

        # Minimal mocks for DecisionResult
        decision            = MagicMock()
        decision.direction  = "LONG"
        decision.regime     = "TREND"
        decision.oi_delta   = 0.01
        decision.funding_rate = 0.0001
        decision.confidence = 0.78
        decision.score      = 7
        decision.entry_price = 50_000.0
        decision.stop_loss  = 49_500.0
        decision.take_profit = 51_000.0
        decision.mtf_aligned = True
        decision.block_reasons = []

        smc         = SMCSignals()
        smc.bos     = True
        smc.choch   = True
        smc.fvg     = True
        smc.ob      = False
        vol         = VolumeSignals()
        vol.volume_spike = True

        with patch("analytics.trade_journal.settings") as ms:
            ms.SYMBOL = "BTCUSDT"
            rec = TradeRecord.from_decision(decision, smc, vol, execution=None)

        assert rec.direction   == "LONG"
        assert rec.bos         == 1
        assert rec.result      == "OPEN"
        assert rec.volume_spike == 1


# ─────────────────────────────────────────────────────────────────────────────
# Strategy (SMC_OI_Regime_Strategy)
# ─────────────────────────────────────────────────────────────────────────────

class TestStrategy:

    def test_import(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        assert SMC_OI_Regime_Strategy is not None

    def test_generate_signal_returns_tuple(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        from decision.brain_decision_engine import DecisionResult

        # Mock all dependencies so no real API call is made
        dec_result         = DecisionResult()
        dec_result.action  = "LONG"
        dec_result.stop_loss   = 49_000.0
        dec_result.take_profit = 52_000.0

        mock_de  = MagicMock(); mock_de.decide.return_value = dec_result
        mock_re  = MagicMock()
        mock_re.classify.return_value = MagicMock(regime="TREND", confidence=0.8)

        mock_smc = MagicMock()
        mock_smc.analyze_mtf.return_value = {}

        mock_vol = MagicMock()
        mock_vol.analyze.return_value = MagicMock()

        mock_dp  = MagicMock()
        mock_dp.get_all_market_data.return_value = {
            "ohlcv":            {"h4": pd.DataFrame(), "h1": pd.DataFrame(), "m15": pd.DataFrame()},
            "mark_price":       50_000.0,
            "oi_delta":         0.01,
            "funding_rate":     0.0001,
            "long_short_ratio": {"longShortRatio": 1.0},
            "taker_ratio":      {"buySellRatio": 1.0},
        }

        strategy = SMC_OI_Regime_Strategy(mock_de, mock_re, mock_smc, mock_vol, mock_dp)
        direction, sl, tp = strategy.generate_signal()

        assert direction in (-1, 0, 1)
        assert isinstance(sl, float)
        assert isinstance(tp, float)

    def test_generate_signal_long_returns_1(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        from decision.brain_decision_engine import DecisionResult

        dec        = DecisionResult()
        dec.action = "LONG"
        dec.stop_loss   = 49_000.0
        dec.take_profit = 52_000.0

        mock_de = MagicMock(); mock_de.decide.return_value = dec
        mock_re = MagicMock()
        mock_re.classify.return_value = MagicMock(regime="TREND", confidence=0.7)
        mock_smc = MagicMock(); mock_smc.analyze_mtf.return_value = {}
        mock_vol = MagicMock(); mock_vol.analyze.return_value = MagicMock()
        mock_dp  = MagicMock()
        mock_dp.get_all_market_data.return_value = {
            "ohlcv": {"h4": pd.DataFrame(), "h1": pd.DataFrame(), "m15": pd.DataFrame()},
            "mark_price": 50_000.0, "oi_delta": 0.01,
            "funding_rate": 0.0001, "long_short_ratio": {},
        }

        strat = SMC_OI_Regime_Strategy(mock_de, mock_re, mock_smc, mock_vol, mock_dp)
        direction, sl, tp = strat.generate_signal()
        assert direction == 1
        assert sl  == 49_000.0
        assert tp  == 52_000.0

    def test_generate_signal_short_returns_minus1(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        from decision.brain_decision_engine import DecisionResult

        dec        = DecisionResult()
        dec.action = "SHORT"
        dec.stop_loss   = 51_000.0
        dec.take_profit = 48_000.0

        mock_de = MagicMock(); mock_de.decide.return_value = dec
        mock_re = MagicMock()
        mock_re.classify.return_value = MagicMock(regime="TREND", confidence=0.7)
        mock_smc = MagicMock(); mock_smc.analyze_mtf.return_value = {}
        mock_vol = MagicMock(); mock_vol.analyze.return_value = MagicMock()
        mock_dp  = MagicMock()
        mock_dp.get_all_market_data.return_value = {
            "ohlcv": {"h4": pd.DataFrame(), "h1": pd.DataFrame(), "m15": pd.DataFrame()},
            "mark_price": 50_000.0, "oi_delta": 0.01,
            "funding_rate": -0.0001, "long_short_ratio": {},
        }

        strat = SMC_OI_Regime_Strategy(mock_de, mock_re, mock_smc, mock_vol, mock_dp)
        direction, sl, tp = strat.generate_signal()
        assert direction == -1

    def test_generate_signal_skip_returns_0(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        from decision.brain_decision_engine import DecisionResult

        dec        = DecisionResult()
        dec.action = "SKIP"

        mock_de = MagicMock(); mock_de.decide.return_value = dec
        mock_re = MagicMock()
        mock_re.classify.return_value = MagicMock(regime="RANGE", confidence=0.6)
        mock_smc = MagicMock(); mock_smc.analyze_mtf.return_value = {}
        mock_vol = MagicMock(); mock_vol.analyze.return_value = MagicMock()
        mock_dp  = MagicMock()
        mock_dp.get_all_market_data.return_value = {
            "ohlcv": {"h4": pd.DataFrame(), "h1": pd.DataFrame(), "m15": pd.DataFrame()},
            "mark_price": 50_000.0, "oi_delta": 0.0,
            "funding_rate": 0.0, "long_short_ratio": {},
        }

        strat     = SMC_OI_Regime_Strategy(mock_de, mock_re, mock_smc, mock_vol, mock_dp)
        direction, sl, tp = strat.generate_signal()
        assert direction == 0
        assert sl == 0.0
        assert tp == 0.0

    def test_generate_signal_exception_returns_0(self):
        from execution.strategy import SMC_OI_Regime_Strategy

        mock_dp = MagicMock()
        mock_dp.get_all_market_data.side_effect = RuntimeError("API down")

        strat = SMC_OI_Regime_Strategy(
            MagicMock(), MagicMock(), MagicMock(), MagicMock(), mock_dp
        )
        direction, sl, tp = strat.generate_signal()
        assert direction == 0

    def test_last_decision_stored(self):
        from execution.strategy import SMC_OI_Regime_Strategy
        from decision.brain_decision_engine import DecisionResult

        dec        = DecisionResult()
        dec.action = "WAIT"

        mock_de = MagicMock(); mock_de.decide.return_value = dec
        mock_re = MagicMock()
        mock_re.classify.return_value = MagicMock(regime="RANGE", confidence=0.5)
        mock_smc = MagicMock(); mock_smc.analyze_mtf.return_value = {}
        mock_vol = MagicMock(); mock_vol.analyze.return_value = MagicMock()
        mock_dp  = MagicMock()
        mock_dp.get_all_market_data.return_value = {
            "ohlcv": {"h4": pd.DataFrame(), "h1": pd.DataFrame(), "m15": pd.DataFrame()},
            "mark_price": 50_000.0, "oi_delta": 0.0,
            "funding_rate": 0.0, "long_short_ratio": {},
        }

        strat = SMC_OI_Regime_Strategy(mock_de, mock_re, mock_smc, mock_vol, mock_dp)
        strat.generate_signal()
        assert strat.last_decision is not None
        assert strat.last_decision.action == "WAIT"
