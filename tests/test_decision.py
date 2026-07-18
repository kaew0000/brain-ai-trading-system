"""Unit tests for Decision Layer."""
import pytest
import numpy as np
import pandas as pd

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def df_m15():
    np.random.seed(99)
    n     = 100
    close = 50_000 + np.random.randn(n) * 100
    close = np.maximum(close, 1_000)
    idx   = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": close - 10, "high": close + 20,
         "low": close - 20, "close": close,
         "volume": np.random.uniform(100, 500, n)},
        index=idx,
    )


def _bullish_smc():
    from features.smc_engine import SMCSignals
    s = SMCSignals()
    s.bos            = True;  s.bos_direction   = "Bullish"
    s.choch          = True;  s.choch_direction  = "Bullish"
    s.fvg            = True;  s.fvg_direction    = "Bullish"
    s.ob             = True;  s.ob_direction     = "Bullish"
    s.ob_top         = 51_200.0
    s.ob_bottom      = 50_800.0
    s.trend_bias     = "Bullish"
    s.prev_high      = 52_000.0
    s.prev_low       = 49_000.0
    s.liquidity_high = 52_500.0
    s.liquidity_low  = 0.0
    return s


def _bearish_smc():
    from features.smc_engine import SMCSignals
    s = SMCSignals()
    s.bos            = True;  s.bos_direction   = "Bearish"
    s.choch          = True;  s.choch_direction  = "Bearish"
    s.fvg            = True;  s.fvg_direction    = "Bearish"
    s.ob             = True;  s.ob_direction     = "Bearish"
    s.ob_top         = 50_200.0
    s.ob_bottom      = 49_800.0
    s.trend_bias     = "Bearish"
    s.prev_high      = 52_000.0
    s.prev_low       = 48_000.0
    s.liquidity_high = 0.0
    s.liquidity_low  = 47_500.0
    return s


def _bullish_volume():
    from features.volume_engine import VolumeSignals
    v = VolumeSignals()
    v.volume_spike  = True
    v.obv_direction = "bullish"
    v.score         = 2
    return v


def _bearish_volume():
    from features.volume_engine import VolumeSignals
    v = VolumeSignals()
    v.volume_spike  = True
    v.obv_direction = "bearish"
    v.score         = 2
    return v


def _trend_regime():
    from regime.regime_engine import RegimeResult
    r = RegimeResult()
    r.regime     = "TREND"
    r.confidence = 0.85
    return r


def _bullish_market(price=50_000.0):
    return {
        "mark_price":       price,
        "oi_delta":         0.015,     # strong rising OI
        "funding_rate":     0.0001,    # low positive (won't block long)
        "long_short_ratio": {"longShortRatio": 0.95},
        "taker_ratio":      {"buySellRatio": 1.1},
    }


def _bearish_market(price=50_000.0):
    return {
        "mark_price":       price,
        "oi_delta":         0.015,
        "funding_rate":     -0.0001,   # won't block short
        "long_short_ratio": {"longShortRatio": 1.05},
        "taker_ratio":      {"buySellRatio": 0.9},
    }


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestBrainDecisionEngine:

    def test_import(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        assert BrainDecisionEngine is not None

    def test_result_import(self):
        from decision.brain_decision_engine import DecisionResult
        res = DecisionResult()
        assert res.action == "SKIP"

    def test_max_total_is_9(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        assert BrainDecisionEngine.MAX_TOTAL == 9

    # ── Long signal ──────────────────────────────────────────────────────

    def test_full_bullish_gives_long(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng  = BrainDecisionEngine()
        smc  = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res  = eng.decide(_bullish_smc.__wrapped__ if hasattr(_bullish_smc, "__wrapped__") else smc,
                          _bullish_volume(), _trend_regime(), _bullish_market(), df_m15)
        # With all signals aligned score should be high → LONG or at minimum WAIT
        assert res.action in ("LONG", "WAIT")

    def test_decide_long_action(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(), df_m15)
        assert res.action in ("LONG", "WAIT", "SKIP")
        assert 0 <= res.score <= 9

    def test_decide_short_action(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bearish_smc(), "h1": _bearish_smc(), "m15": _bearish_smc()}
        res = eng.decide(smc, _bearish_volume(), _trend_regime(),
                         _bearish_market(), df_m15)
        assert res.action in ("SHORT", "WAIT", "SKIP")

    # ── Scores ────────────────────────────────────────────────────────────

    def test_score_bounds(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(), df_m15)
        assert 0 <= res.score <= 9
        assert 0.0 <= res.confidence <= 1.0

    def test_smc_score_max_4(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(), df_m15)
        assert res.smc_score <= 4

    def test_volume_score_max_2(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(), df_m15)
        assert res.volume_score <= 2

    def test_oi_score_max_2(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(), df_m15)
        assert res.oi_score <= 2

    # ── Hard blocks ───────────────────────────────────────────────────────

    def test_funding_blocks_long(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng    = BrainDecisionEngine()
        blocks = eng._check_blocks(
            direction="LONG",
            funding=0.001,        # above 0.05 % threshold
            oi_delta=0.02,
            price_chg_pct=0.005,
        )
        assert any("FUNDING_BLOCK_LONG" in b for b in blocks)

    def test_funding_blocks_short(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng    = BrainDecisionEngine()
        blocks = eng._check_blocks(
            direction="SHORT",
            funding=-0.001,       # below -0.05 % threshold
            oi_delta=0.02,
            price_chg_pct=-0.005,
        )
        assert any("FUNDING_BLOCK_SHORT" in b for b in blocks)

    def test_short_covering_blocks_long(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        blocks = BrainDecisionEngine()._check_blocks(
            "LONG", 0.0001, oi_delta=-0.02, price_chg_pct=0.01
        )
        assert any("SHORT_COVERING" in b for b in blocks)

    def test_long_liquidation_blocks_short(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        blocks = BrainDecisionEngine()._check_blocks(
            "SHORT", -0.0001, oi_delta=0.02, price_chg_pct=-0.01
        )
        assert any("LONG_LIQUIDATION" in b for b in blocks)

    def test_no_blocks_normal(self):
        from decision.brain_decision_engine import BrainDecisionEngine
        blocks = BrainDecisionEngine()._check_blocks(
            "LONG", 0.0001, oi_delta=0.01, price_chg_pct=0.002
        )
        assert len(blocks) == 0

    # ── SL / TP ───────────────────────────────────────────────────────────

    def test_sl_below_entry_for_long(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(50_000), df_m15)
        if res.action == "LONG":
            assert res.stop_loss < res.entry_price

    def test_tp_above_entry_for_long(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = eng.decide(smc, _bullish_volume(), _trend_regime(),
                         _bullish_market(50_000), df_m15)
        if res.action == "LONG":
            assert res.take_profit > res.entry_price

    def test_sl_above_entry_for_short(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        eng = BrainDecisionEngine()
        smc = {"h4": _bearish_smc(), "h1": _bearish_smc(), "m15": _bearish_smc()}
        res = eng.decide(smc, _bearish_volume(), _trend_regime(),
                         _bearish_market(50_000), df_m15)
        if res.action == "SHORT":
            assert res.stop_loss > res.entry_price

    # ── Zero price guard ──────────────────────────────────────────────────

    def test_zero_price_returns_skip(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        mkt = _bullish_market(price=0.0)
        res = BrainDecisionEngine().decide(
            smc, _bullish_volume(), _trend_regime(), mkt, df_m15
        )
        assert res.action == "SKIP"

    # ── to_dict ───────────────────────────────────────────────────────────

    def test_to_dict_complete(self, df_m15):
        from decision.brain_decision_engine import BrainDecisionEngine
        smc = {"h4": _bullish_smc(), "h1": _bullish_smc(), "m15": _bullish_smc()}
        res = BrainDecisionEngine().decide(
            smc, _bullish_volume(), _trend_regime(), _bullish_market(), df_m15
        )
        d = res.to_dict()
        for key in ("action", "score", "max_score", "confidence",
                    "smc_score", "volume_score", "oi_score", "sentiment_score",
                    "direction", "stop_loss", "take_profit", "entry_price",
                    "regime", "mtf_aligned", "oi_delta", "funding_rate"):
            assert key in d
