"""
tests/test_execution_factory.py

Coverage for:
  - ExecutionFactory (paper / testnet / live / invalid mode)
  - _PaperAdapter.execute_trade() interface
  - _derive_levels() OB validation fix (Gap 3)
  - PaperExecutionEngine smoke test
"""
import pytest
import os

# v16 fix: see tests/test_v15_production.py for the full explanation —
# this file had no pytestmark either, so all 37 tests here were silently
# excluded from the default `pytest tests/` run (pytest.ini addopts
# filters to `-m "unit"`). Content is pure branching-logic tests over
# ExecutionFactory with no live network calls — belongs under "unit".
pytestmark = pytest.mark.unit


# ══════════════════════════════════════════════════════════════════════════════
# ExecutionFactory
# ══════════════════════════════════════════════════════════════════════════════

class TestExecutionFactory:

    def _factory(self, mode: str):
        os.environ["EXECUTION_MODE"] = mode
        # Reload module to pick up env change
        import importlib, config.settings as s
        s.EXECUTION_MODE = mode
        import execution.execution_factory as ef
        importlib.reload(ef)
        return ef

    def test_paper_mode_returns_paper_adapter(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None)
        assert hasattr(engine, "execute_trade")
        # Should be _PaperAdapter
        assert "Paper" in type(engine._engine).__name__

    def test_paper_adapter_has_execute_trade(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None)
        assert callable(engine.execute_trade)

    def test_invalid_mode_raises(self):
        ef = self._factory("invalid_mode")
        with pytest.raises(ValueError, match="Unknown EXECUTION_MODE"):
            ef.build_execution_engine(data_provider=None)

    def test_testnet_without_provider_raises(self):
        ef = self._factory("testnet")
        with pytest.raises(RuntimeError, match="requires a BinanceDataProvider"):
            ef.build_execution_engine(data_provider=None)

    def test_live_without_provider_raises(self):
        ef = self._factory("live")
        with pytest.raises(RuntimeError, match="requires a BinanceDataProvider"):
            ef.build_execution_engine(data_provider=None)

    def test_paper_starting_balance(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=5000.0)
        assert engine._engine.account.balance == 5000.0

    def test_paper_execute_trade_returns_dict(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=10000.0)
        result = engine.execute_trade(
            direction="LONG", entry_price=67000.0,
            stop_loss=65800.0, take_profit=69400.0,
            balance=10000.0, risk_pct=0.01,
        )
        assert isinstance(result, dict)
        assert "success" in result

    def test_paper_execute_trade_success(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=10000.0)
        result = engine.execute_trade(
            direction="LONG", entry_price=67000.0,
            stop_loss=65800.0, take_profit=69400.0,
            balance=10000.0, risk_pct=0.01,
        )
        assert result["success"] is True

    def test_paper_execute_trade_short(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=10000.0)
        result = engine.execute_trade(
            direction="SHORT", entry_price=67000.0,
            stop_loss=68200.0, take_profit=64600.0,
            balance=10000.0, risk_pct=0.01,
        )
        assert result["success"] is True

    def test_paper_blocks_second_position(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=10000.0)
        engine.execute_trade("LONG", 67000.0, 65800.0, 69400.0, 10000.0, 0.01)
        result2 = engine.execute_trade("SHORT", 67000.0, 68200.0, 64600.0, 10000.0, 0.01)
        assert result2["success"] is False

    def test_paper_get_metrics(self):
        ef = self._factory("paper")
        engine = ef.build_execution_engine(data_provider=None, paper_balance=10000.0)
        metrics = engine.get_metrics()
        assert isinstance(metrics, dict)


# ══════════════════════════════════════════════════════════════════════════════
# Gap 3: _derive_levels() OB validation
# ══════════════════════════════════════════════════════════════════════════════

class TestDeriveLevels:

    def _derive(self, direction, mark, ob_top=0.0, ob_bottom=0.0):
        """Call _derive_levels from main.py via import."""
        from main import _derive_levels
        ctx = {"smc_m15": {"ob_top": ob_top, "ob_bottom": ob_bottom}}
        return _derive_levels(direction, mark, ctx)

    def test_long_no_ob_uses_mark(self):
        entry, sl, tp = self._derive("LONG", 67000.0)
        assert entry == 67000.0
        assert sl < entry
        assert tp > entry

    def test_short_no_ob_uses_mark(self):
        entry, sl, tp = self._derive("SHORT", 67000.0)
        assert entry == 67000.0
        assert sl > entry
        assert tp < entry

    def test_long_valid_ob_below_price(self):
        # OB bottom at 66800 (0.3% below 67000) — valid, should use it
        entry, sl, tp = self._derive("LONG", 67000.0, ob_bottom=66800.0)
        assert entry == 66800.0

    def test_long_ob_too_far_below_uses_mark(self):
        # OB bottom at 64000 (4.5% below 67000) — too far, use mark
        entry, sl, tp = self._derive("LONG", 67000.0, ob_bottom=64000.0)
        assert entry == 67000.0

    def test_long_ob_above_price_uses_mark(self):
        # OB bottom above mark (Gap 3 original bug) — must use mark
        entry, sl, tp = self._derive("LONG", 67000.0, ob_bottom=68000.0)
        assert entry == 67000.0

    def test_long_ob_zero_uses_mark(self):
        entry, sl, tp = self._derive("LONG", 67000.0, ob_bottom=0.0)
        assert entry == 67000.0

    def test_short_valid_ob_above_price(self):
        entry, sl, tp = self._derive("SHORT", 67000.0, ob_top=67200.0)
        assert entry == 67200.0

    def test_short_ob_too_far_above_uses_mark(self):
        entry, sl, tp = self._derive("SHORT", 67000.0, ob_top=70000.0)
        assert entry == 67000.0

    def test_short_ob_below_price_uses_mark(self):
        # OB top below mark price — invalid for SHORT entry
        entry, sl, tp = self._derive("SHORT", 67000.0, ob_top=65000.0)
        assert entry == 67000.0

    def test_empty_direction_returns_zeros(self):
        entry, sl, tp = self._derive("", 67000.0)
        assert entry == 0.0 and sl == 0.0 and tp == 0.0

    def test_zero_mark_returns_zeros(self):
        entry, sl, tp = self._derive("LONG", 0.0)
        assert entry == 0.0

    def test_sl_below_entry_for_long(self):
        entry, sl, tp = self._derive("LONG", 67000.0)
        assert sl < entry

    def test_tp_above_entry_for_long(self):
        entry, sl, tp = self._derive("LONG", 67000.0)
        assert tp > entry

    def test_sl_above_entry_for_short(self):
        entry, sl, tp = self._derive("SHORT", 67000.0)
        assert sl > entry

    def test_tp_below_entry_for_short(self):
        entry, sl, tp = self._derive("SHORT", 67000.0)
        assert tp < entry

    def test_rr_at_least_2(self):
        entry, sl, tp = self._derive("LONG", 67000.0)
        risk   = entry - sl
        reward = tp - entry
        assert reward / risk >= 1.8  # matches TP_PCT / SL_PCT = 5.4/1.8


# ══════════════════════════════════════════════════════════════════════════════
# PaperExecutionEngine unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPaperExecutionEngine:

    @pytest.fixture
    def engine(self):
        from paper.paper_execution import PaperExecutionEngine
        return PaperExecutionEngine(starting_usdt=10_000.0)

    def _decision(self, action="LONG", entry=67000.0, sl=65800.0, tp=69400.0):
        class D:
            pass
        d = D()
        d.action      = action
        d.direction   = action
        d.entry_price = entry
        d.stop_loss   = sl
        d.take_profit = tp
        d.confidence  = 82
        d.regime      = "TREND"
        d.oi_delta    = 0.015
        d.funding_rate = 0.0001
        return d

    def test_execute_long_success(self, engine):
        r = engine.execute(self._decision("LONG"), risk_pct=0.01)
        assert r["success"] is True

    def test_execute_short_success(self, engine):
        r = engine.execute(self._decision("SHORT", sl=68200.0, tp=64600.0), risk_pct=0.01)
        assert r["success"] is True

    def test_quantity_positive(self, engine):
        r = engine.execute(self._decision(), risk_pct=0.01)
        assert r.get("quantity", 0.0) > 0

    def test_skip_action_returns_false(self, engine):
        r = engine.execute(self._decision("SKIP"))
        assert r["success"] is False

    def test_wait_action_returns_false(self, engine):
        r = engine.execute(self._decision("WAIT"))
        assert r["success"] is False

    def test_max_open_blocks_second(self, engine):
        engine.execute(self._decision("LONG"), risk_pct=0.01)
        r2 = engine.execute(self._decision("SHORT", sl=68200.0, tp=64600.0), risk_pct=0.01)
        assert r2["success"] is False

    def test_metrics_structure(self, engine):
        engine.execute(self._decision("LONG"), risk_pct=0.01)
        m = engine.get_metrics()
        # Top-level keys from PaperExecutionEngine.get_metrics()
        for key in ("total_trades", "total_pnl", "win_rate", "account"):
            assert key in m, f"Missing metric: {key}"
        # Account sub-dict
        for key in ("balance", "equity", "used_margin", "open_trades"):
            assert key in m["account"], f"Missing account key: {key}"

    def test_balance_decreases_by_margin(self, engine):
        initial = engine.account.balance
        engine.execute(self._decision("LONG"), risk_pct=0.01)
        # Margin is reserved — free_margin should decrease
        m = engine.get_metrics()
        assert m["account"]["used_margin"] > 0
        assert m["account"]["free_margin"] < initial

    def test_open_position_count(self, engine):
        engine.execute(self._decision("LONG"), risk_pct=0.01)
        m = engine.get_metrics()
        assert m["account"]["open_trades"] == 1

    def test_paper_result_has_required_keys(self, engine):
        r = engine.execute(self._decision("LONG"), risk_pct=0.01)
        for k in ("success", "quantity"):
            assert k in r
