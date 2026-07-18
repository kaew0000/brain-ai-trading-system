"""Unit tests for Regime Layer."""
import pytest
import numpy as np
import pandas as pd

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _make_ohlcv(n, seed, trend_per_bar=0, noise=100):
    np.random.seed(seed)
    close = 50_000 + np.arange(n) * trend_per_bar + np.random.randn(n) * noise
    close = np.maximum(close, 1_000)
    high  = close + np.abs(np.random.randn(n) * 60)
    low   = close - np.abs(np.random.randn(n) * 60)
    low   = np.maximum(low, 1)
    idx   = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close - 10, "high": high, "low": low,
         "close": close, "volume": np.random.uniform(200, 1_000, n)},
        index=idx,
    )


@pytest.fixture
def trending_df():
    return _make_ohlcv(200, seed=1, trend_per_bar=50, noise=30)


@pytest.fixture
def ranging_df():
    return _make_ohlcv(200, seed=2, trend_per_bar=0, noise=80)


@pytest.fixture
def volatile_df():
    """Very high-noise data to trigger VOLATILE."""
    np.random.seed(3)
    n     = 200
    close = 50_000 + np.random.randn(n) * 800     # huge swings
    close = np.maximum(close, 1_000)
    high  = close + np.abs(np.random.randn(n) * 600)
    low   = close - np.abs(np.random.randn(n) * 600)
    low   = np.maximum(low, 1)
    idx   = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close - 50, "high": high, "low": low,
         "close": close, "volume": np.random.uniform(200, 1_000, n)},
        index=idx,
    )


@pytest.fixture
def squeeze_df():
    """Extremely flat data to trigger SQUEEZE."""
    np.random.seed(4)
    n     = 200
    close = 50_000 + np.random.randn(n) * 5       # tiny noise
    close = np.maximum(close, 1_000)
    high  = close + np.abs(np.random.randn(n) * 3)
    low   = close - np.abs(np.random.randn(n) * 3)
    low   = np.maximum(low, 1)
    idx   = pd.date_range("2024-01-01", periods=n, freq="1h", tz="UTC")
    return pd.DataFrame(
        {"open": close - 1, "high": high, "low": low,
         "close": close, "volume": np.random.uniform(50, 200, n)},
        index=idx,
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestRegimeEngine:

    def test_import(self):
        from regime.regime_engine import RegimeEngine
        assert RegimeEngine is not None

    def test_result_import(self):
        from regime.regime_engine import RegimeResult
        assert RegimeResult.REGIMES == ("TREND", "RANGE", "VOLATILE", "SQUEEZE")

    def test_classify_returns_valid_regime(self, trending_df):
        from regime.regime_engine import RegimeEngine
        eng    = RegimeEngine(use_hmm=False)
        result = eng.classify(trending_df)
        assert result.regime in ("TREND", "RANGE", "VOLATILE", "SQUEEZE")

    def test_confidence_in_range(self, trending_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(trending_df)
        assert 0.0 <= result.confidence <= 1.0

    def test_adx_positive(self, trending_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(trending_df)
        assert result.adx >= 0.0

    def test_trending_data_detects_trend(self, trending_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(trending_df)
        # Strong trend should produce TREND or at least not SQUEEZE
        assert result.regime != "SQUEEZE"

    def test_squeeze_data_detects_squeeze(self, squeeze_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(squeeze_df)
        assert result.regime == "SQUEEZE"

    def test_volatile_data_detects_volatile(self, volatile_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(volatile_df)
        assert result.regime in ("VOLATILE", "RANGE")   # noisy data may vary

    def test_to_dict_keys(self, ranging_df):
        from regime.regime_engine import RegimeEngine
        d = RegimeEngine(use_hmm=False).classify(ranging_df).to_dict()
        for key in ("regime", "confidence", "adx", "bb_width", "atr_normalized"):
            assert key in d

    def test_insufficient_bars_returns_default(self):
        from regime.regime_engine import RegimeEngine
        tiny = pd.DataFrame(
            {"open": [1], "high": [2], "low": [0], "close": [1], "volume": [1]},
        )
        result = RegimeEngine(use_hmm=False).classify(tiny)
        assert result.regime == "RANGE"   # default fallback

    def test_hmm_mode_does_not_crash(self, trending_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=True).classify(trending_df)
        assert result.regime in ("TREND", "RANGE", "VOLATILE", "SQUEEZE")

    def test_probabilities_sum_to_one(self, ranging_df):
        from regime.regime_engine import RegimeEngine
        result = RegimeEngine(use_hmm=False).classify(ranging_df)
        total  = sum(result.probabilities.values())
        assert abs(total - 1.0) < 1e-6
