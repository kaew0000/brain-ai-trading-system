"""
tests/test_p1b1_dynamic_risk.py — P1-B1 Dynamic Risk Engine (single symbol)

Covers the volatility-aware additions to RiskEngine (get_leverage(),
atr_pct-scaled get_risk_pct()/report()) and the leverage wiring through
TradeManager.calculate_position_size()/execute_trade() and the paper
execution adapter.

Every new parameter here (atr_pct, leverage) is optional and defaults to
None — the "atr_pct=None reproduces old behavior exactly" tests below are
the regression guard for that contract, since main.py, the dashboard/API
report() call sites, and ~8 pre-existing direct RiskEngine(...) test call
sites all still call these methods without the new arguments.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# RiskEngine: volatility factor, dynamic risk %, dynamic leverage
# ─────────────────────────────────────────────────────────────────────────────

def _make_journal(pnl=0.0, streak=0, trades=0, win_rate=0.0):
    """Mirrors TestRiskEngine._make_journal in test_execution.py."""
    j = MagicMock()
    j.get_today_pnl.return_value          = pnl
    j.get_consecutive_losses.return_value = streak
    j.get_daily_stats.return_value        = {
        "total_pnl": pnl, "total_trades": trades, "win_rate": win_rate,
    }
    return j


def _mock_settings(ms, threshold=0.015, floor=0.5, leverage=5,
                    risk_min=0.005, risk_max=0.01, max_daily_loss=0.03,
                    max_consec_losses=3):
    """Fully populate risk.risk_engine.settings for tests that exercise
    atr_pct-driven comparisons (which the leaner mocks in test_execution.py
    can skip, since they only pass atr_pct=None and short-circuit before
    touching these fields)."""
    ms.MAX_DAILY_LOSS             = max_daily_loss
    ms.MAX_CONSECUTIVE_LOSSES     = max_consec_losses
    ms.RISK_PER_TRADE_MIN         = risk_min
    ms.RISK_PER_TRADE_MAX         = risk_max
    ms.LEVERAGE                   = leverage
    ms.VOLATILITY_RISK_THRESHOLD  = threshold
    ms.VOLATILITY_RISK_FLOOR      = floor


class TestVolatilityFactor:

    def test_none_atr_is_full_factor(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms)
            eng = RiskEngine(_make_journal())
            assert eng._volatility_factor(None) == 1.0

    def test_atr_at_or_below_threshold_is_full_factor(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, threshold=0.015)
            eng = RiskEngine(_make_journal())
            assert eng._volatility_factor(0.015) == 1.0
            assert eng._volatility_factor(0.010) == 1.0

    def test_atr_above_threshold_scales_down(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, threshold=0.015, floor=0.5)
            eng = RiskEngine(_make_journal())
            # atr_pct = 2x threshold -> raw factor 0.5, exactly at the floor
            factor = eng._volatility_factor(0.030)
            assert factor == pytest.approx(0.5)

    def test_extreme_atr_clamped_at_floor_not_below(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, threshold=0.015, floor=0.5)
            eng = RiskEngine(_make_journal())
            # atr_pct = 10x threshold -> raw factor 0.1, must clamp to floor 0.5
            factor = eng._volatility_factor(0.150)
            assert factor == pytest.approx(0.5)


class TestDynamicRiskPctVolatility:

    def test_atr_none_matches_pre_p1b1_behavior(self):
        """Regression guard: omitting atr_pct must reproduce the exact
        pre-P1-B1 2-tier value, for every existing caller that doesn't
        know about atr_pct yet."""
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, risk_min=0.005, risk_max=0.01)
            eng = RiskEngine(_make_journal(streak=0, pnl=0.0))
            assert eng.get_risk_pct(1_000.0) == 0.01          # MAX tier
            assert eng.get_risk_pct(1_000.0, atr_pct=None) == 0.01

    def test_high_volatility_reduces_risk_pct_below_max(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, threshold=0.015, floor=0.5, risk_min=0.005, risk_max=0.01)
            eng = RiskEngine(_make_journal(streak=0, pnl=0.0))
            calm   = eng.get_risk_pct(1_000.0, atr_pct=0.010)   # below threshold
            volatile = eng.get_risk_pct(1_000.0, atr_pct=0.030)  # 2x threshold
            assert calm == 0.01
            assert volatile < calm
            assert volatile >= 0.005                            # never below MIN

    def test_streak_min_unaffected_by_volatility(self):
        """When the streak-based path already selects MIN, volatility
        scaling must not push it any lower (MIN is the absolute floor)."""
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, threshold=0.015, floor=0.5, risk_min=0.005, risk_max=0.01)
            eng = RiskEngine(_make_journal(streak=3, pnl=0.0))
            assert eng.get_risk_pct(1_000.0, atr_pct=0.10) == 0.005


class TestDynamicLeverage:

    def test_atr_none_returns_base_leverage(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, leverage=5)
            eng = RiskEngine(_make_journal())
            assert eng.get_leverage() == 5
            assert eng.get_leverage(atr_pct=None) == 5

    def test_high_volatility_reduces_leverage(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, leverage=10, threshold=0.015, floor=0.5)
            eng = RiskEngine(_make_journal())
            lev = eng.get_leverage(atr_pct=0.030)  # 2x threshold -> factor 0.5
            assert lev == 5                         # round(10 * 0.5)

    def test_leverage_never_below_one(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, leverage=1, threshold=0.015, floor=0.5)
            eng = RiskEngine(_make_journal())
            lev = eng.get_leverage(atr_pct=0.150)  # extreme volatility
            assert lev >= 1


class TestReportIncludesVolatilityFields:

    def test_report_backward_compatible_keys_unchanged(self):
        """Every pre-P1-B1 key must still be present with the same meaning
        — agents/risk_manager.py reads this dict and must keep working
        unmodified."""
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms)
            eng = RiskEngine(_make_journal())
            rpt = eng.report(1_000.0)
        for key in ("can_trade", "block_reason", "disabled_today",
                    "consecutive_losses", "today_pnl", "today_trades",
                    "today_win_rate", "max_daily_loss_u", "dynamic_risk_pct"):
            assert key in rpt

    def test_report_new_volatility_keys(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, leverage=5, threshold=0.015, floor=0.5)
            eng = RiskEngine(_make_journal())
            rpt = eng.report(1_000.0, atr_pct=0.030)
        assert rpt["atr_pct"] == 0.030
        # round(5 * 0.5) == round(2.5) == 2 (Python's banker's rounding —
        # round-half-to-even, not round-half-up).
        assert rpt["dynamic_leverage"] == 2
        assert rpt["volatility_factor"] == pytest.approx(0.5)

    def test_report_atr_none_defaults(self):
        from risk.risk_engine import RiskEngine
        with patch("risk.risk_engine.settings") as ms:
            _mock_settings(ms, leverage=5)
            eng = RiskEngine(_make_journal())
            rpt = eng.report(1_000.0)
        assert rpt["atr_pct"] is None
        assert rpt["volatility_factor"] == 1.0
        assert rpt["dynamic_leverage"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# TradeManager: leverage wiring into position sizing and execute_trade
# ─────────────────────────────────────────────────────────────────────────────

def _make_manager():
    """Build a TradeManager with a fully mocked client (mirrors
    test_execution.py / test_v16_execution_idempotency.py)."""
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
    mock_provider       = MagicMock()
    mock_provider.client = mock_client

    with patch("execution.trade_manager.settings") as ms:
        ms.SYMBOL              = "BTCUSDT"
        ms.LEVERAGE            = 5
        ms.RISK_PER_TRADE_MAX  = 0.01
        ms.RISK_PER_TRADE_MIN  = 0.005
        ms.MAX_MARGIN_USAGE    = 0.20
        manager = TradeManager(mock_provider)

    manager.client = mock_client
    manager.symbol = "BTCUSDT"
    return manager, mock_client


class TestPositionSizeLeverageParam:

    def test_omitted_leverage_uses_settings_leverage_for_margin_cap(self):
        """Regression guard: identical result to pre-P1-B1 when leverage
        isn't passed."""
        m, _ = _make_manager()
        with patch("execution.trade_manager.settings") as ms:
            ms.RISK_PER_TRADE_MAX = 0.01
            ms.MAX_MARGIN_USAGE   = 0.20
            ms.LEVERAGE           = 5
            qty_default = m.calculate_position_size(1_000.0, 50_000.0, 49_000.0)
            qty_explicit_same = m.calculate_position_size(
                1_000.0, 50_000.0, 49_000.0, leverage=5
            )
        assert qty_default == qty_explicit_same

    def test_lower_leverage_tightens_margin_cap(self):
        """A wide risk-based qty should get capped harder at lower leverage
        (smaller max_notional) than at higher leverage, when the margin cap
        is the binding constraint."""
        m, _ = _make_manager()
        with patch("execution.trade_manager.settings") as ms:
            ms.RISK_PER_TRADE_MAX = 0.5   # deliberately large so margin cap binds
            ms.MAX_MARGIN_USAGE   = 0.20
            ms.LEVERAGE           = 20
            qty_low_lev  = m.calculate_position_size(
                1_000.0, 50_000.0, 49_900.0, risk_pct=0.5, leverage=2
            )
            qty_high_lev = m.calculate_position_size(
                1_000.0, 50_000.0, 49_900.0, risk_pct=0.5, leverage=20
            )
        assert qty_low_lev < qty_high_lev


class TestExecuteTradeLeverageParam:

    def test_execute_trade_sends_dynamic_leverage_to_exchange(self):
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}

        with patch("execution.trade_manager.time.sleep"), \
             patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL             = "BTCUSDT"
            ms.LEVERAGE           = 5
            ms.RISK_PER_TRADE_MAX = 0.01
            ms.RISK_PER_TRADE_MIN = 0.005
            ms.MAX_MARGIN_USAGE   = 0.20
            m.execute_trade(
                direction="LONG", entry_price=50_000.0,
                stop_loss=49_000.0, take_profit=52_000.0,
                balance=1_000.0, risk_pct=0.01, leverage=3,
            )

        assert client.change_leverage.call_args[1]["leverage"] == 3

    def test_execute_trade_omitted_leverage_uses_settings_default(self):
        """Regression guard: identical exchange call to pre-P1-B1 when
        leverage isn't passed — set_leverage(settings.LEVERAGE)."""
        m, client = _make_manager()
        client.new_order.return_value = {"orderId": 1, "status": "FILLED"}

        with patch("execution.trade_manager.time.sleep"), \
             patch("execution.trade_manager.settings") as ms:
            ms.SYMBOL             = "BTCUSDT"
            ms.LEVERAGE           = 5
            ms.RISK_PER_TRADE_MAX = 0.01
            ms.RISK_PER_TRADE_MIN = 0.005
            ms.MAX_MARGIN_USAGE   = 0.20
            m.execute_trade(
                direction="LONG", entry_price=50_000.0,
                stop_loss=49_000.0, take_profit=52_000.0,
                balance=1_000.0, risk_pct=0.01,
            )

        assert client.change_leverage.call_args[1]["leverage"] == 5


# ─────────────────────────────────────────────────────────────────────────────
# Paper execution adapter: interface parity with TradeManager.execute_trade
# ─────────────────────────────────────────────────────────────────────────────

class TestPaperAdapterAcceptsLeverageParam:

    def test_paper_adapter_does_not_raise_on_leverage_kwarg(self):
        """main.py calls tm.execute_trade(..., leverage=...) unconditionally
        regardless of which engine is active — the paper adapter must accept
        the kwarg even though (documented, out of scope for P1-B1) it
        doesn't forward it to PaperExecutionEngine."""
        from execution.execution_factory import _PaperAdapter

        mock_engine = MagicMock()
        mock_engine.execute.return_value = {"success": True}
        adapter = _PaperAdapter(mock_engine)

        result = adapter.execute_trade(
            direction="LONG", entry_price=50_000.0,
            stop_loss=49_000.0, take_profit=52_000.0,
            balance=1_000.0, risk_pct=0.01, leverage=3,
        )
        assert result == {"success": True}
        # leverage is intentionally NOT forwarded — see the docstring in
        # execution/execution_factory.py for why.
        _, called_kwargs = mock_engine.execute.call_args
        assert "leverage" not in called_kwargs
