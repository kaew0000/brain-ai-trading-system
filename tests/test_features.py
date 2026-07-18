"""Unit tests for Feature Layer (SMC + Volume engines)."""
import pytest
import numpy as np
import pandas as pd

pytestmark = pytest.mark.unit


# ── Shared fixture ────────────────────────────────────────────────────────────

@pytest.fixture
def ohlcv_200():
    """200-bar synthetic OHLCV suitable for all feature tests."""
    np.random.seed(42)
    n = 200
    close = 50_000 + np.cumsum(np.random.randn(n) * 150)
    close = np.maximum(close, 1_000)
    high  = close + np.abs(np.random.randn(n) * 80)
    low   = close - np.abs(np.random.randn(n) * 80)
    low   = np.maximum(low, 1)
    vol   = np.random.uniform(200, 1_500, n)
    idx   = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": close - 20, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


@pytest.fixture
def uptrend_ohlcv():
    """100-bar strong uptrend OHLCV."""
    np.random.seed(1)
    n     = 100
    close = 50_000 + np.arange(n) * 30 + np.random.randn(n) * 5
    high  = close + 20
    low   = close - 20
    vol   = np.ones(n) * 600
    idx   = pd.date_range("2024-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {"open": close - 5, "high": high, "low": low, "close": close, "volume": vol},
        index=idx,
    )


# ── VolumeEngine ─────────────────────────────────────────────────────────────

class TestVolumeEngine:

    def test_import(self):
        from features.volume_engine import VolumeEngine
        assert VolumeEngine is not None

    def test_returns_signals(self, ohlcv_200):
        from features.volume_engine import VolumeEngine, VolumeSignals
        eng = VolumeEngine(spike_multiplier=2.0, avg_period=20)
        sig = eng.analyze(ohlcv_200)
        assert isinstance(sig, VolumeSignals)

    def test_obv_direction_valid(self, ohlcv_200):
        from features.volume_engine import VolumeEngine
        sig = VolumeEngine().analyze(ohlcv_200)
        assert sig.obv_direction in ("bullish", "bearish", "neutral")

    def test_score_bounded(self, ohlcv_200):
        from features.volume_engine import VolumeEngine
        sig = VolumeEngine().analyze(ohlcv_200)
        assert 0 <= sig.score <= 2

    def test_uptrend_obv_bullish(self, uptrend_ohlcv):
        from features.volume_engine import VolumeEngine
        sig = VolumeEngine().analyze(uptrend_ohlcv)
        assert sig.obv_direction == "bullish"

    def test_insufficient_data(self):
        from features.volume_engine import VolumeEngine
        df  = pd.DataFrame(
            {"open": [1, 2], "high": [2, 3], "low": [0, 1],
             "close": [1.5, 2.5], "volume": [100, 200]},
        )
        sig = VolumeEngine().analyze(df)
        assert sig.score == 0
        assert sig.obv_direction == "neutral"

    def test_direction_hint_scoring(self, uptrend_ohlcv):
        from features.volume_engine import VolumeEngine
        eng      = VolumeEngine()
        sig_long  = eng.analyze(uptrend_ohlcv, direction_hint="LONG")
        sig_short = eng.analyze(uptrend_ohlcv, direction_hint="SHORT")
        # In an uptrend OBV is bullish → LONG should score >= SHORT
        assert sig_long.score >= sig_short.score

    def test_volume_ratio_positive(self, ohlcv_200):
        from features.volume_engine import VolumeEngine
        sig = VolumeEngine().analyze(ohlcv_200)
        assert sig.volume_ratio >= 0

    def test_to_dict_keys(self, ohlcv_200):
        from features.volume_engine import VolumeEngine, VolumeSignals
        sig = VolumeEngine().analyze(ohlcv_200)
        d   = sig.to_dict()
        for key in ("volume_spike", "obv_direction", "divergence",
                    "score", "avg_volume", "current_volume"):
            assert key in d


# ── SMCEngine ─────────────────────────────────────────────────────────────────

class TestSMCEngine:

    def test_import(self):
        try:
            from features.smc_engine import SMCEngine
            assert SMCEngine is not None
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")

    def test_returns_smc_signals(self, ohlcv_200):
        try:
            from features.smc_engine import SMCEngine, SMCSignals
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")
        sig = SMCEngine(swing_hl_count=10).analyze(ohlcv_200, "TEST")
        assert isinstance(sig, SMCSignals)

    def test_boolean_fields(self, ohlcv_200):
        try:
            from features.smc_engine import SMCEngine
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")
        sig = SMCEngine().analyze(ohlcv_200)
        for field in ("bos", "choch", "fvg", "ob"):
            assert isinstance(getattr(sig, field), bool)

    def test_direction_values(self, ohlcv_200):
        try:
            from features.smc_engine import SMCEngine
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")
        sig = SMCEngine().analyze(ohlcv_200)
        for d in (sig.bos_direction, sig.choch_direction,
                  sig.fvg_direction, sig.ob_direction, sig.trend_bias):
            assert d in ("Bullish", "Bearish", "")

    def test_analyze_mtf(self, ohlcv_200):
        try:
            from features.smc_engine import SMCEngine
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")
        eng = SMCEngine()
        out = eng.analyze_mtf({"h4": ohlcv_200, "h1": ohlcv_200, "m15": ohlcv_200})
        assert set(out.keys()) == {"h4", "h1", "m15"}

    def test_invalid_df_raises(self):
        try:
            from features.smc_engine import SMCEngine, SMCSignals
        except ImportError:
            pytest.skip("smartmoneyconcepts not installed")
        eng = SMCEngine()
        bad = pd.DataFrame({"price": [1, 2, 3]})
        # analyze() catches errors internally and returns empty SMCSignals
        sig = eng.analyze(bad)
        # Should return default empty signals (bos=False, ob=False etc.)
        assert isinstance(sig, SMCSignals)
        assert sig.bos   is False
        assert sig.choch is False
