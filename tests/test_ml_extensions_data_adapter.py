"""
Tests for ml/extensions_integration/data_adapter.py

Covers:
  1. compute_feature_frame() always produces exactly 20 named columns
     (BrainTradingEnv hardcodes n_features=20), no NaN/inf leakage.
  2. RLDataPipelineAdapter implements BrainTradingEnv's exact
     data_pipeline contract: get_features(window)/reset()/step()/
     get_current_price()/is_done() — verified against the real
     ml/extensions/rl/env.py, not assumed.
  3. get_features() zero-pads short history the same way
     ml/extensions/example.py's own MockDataPipeline does.
  4. Missing OHLCV columns raise a clear error rather than a confusing
     KeyError deep inside pandas.

All tests are self-contained — synthetic OHLCV only, no network calls,
no live exchange connection.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.extensions_integration.data_adapter import (
    FEATURE_NAMES,
    RLDataPipelineAdapter,
    compute_feature_frame,
)

pytestmark = pytest.mark.unit


def _synthetic_ohlcv(n: int = 200, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + rng.uniform(0, 2, n)
    low = close - rng.uniform(0, 2, n)
    open_ = close + rng.normal(0, 0.5, n)
    volume = rng.uniform(1000, 2000, n)
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close, "volume": volume})


class TestComputeFeatureFrame:
    def test_exactly_20_columns_matching_feature_names(self):
        df = _synthetic_ohlcv()
        features = compute_feature_frame(df)
        assert list(features.columns) == FEATURE_NAMES
        assert features.shape[1] == 20

    def test_same_row_count_as_input(self):
        df = _synthetic_ohlcv(n=150)
        features = compute_feature_frame(df)
        assert len(features) == len(df)

    def test_no_nan_or_inf_leakage(self):
        # Warm-up windows (rolling(20), etc.) produce NaN for the first
        # rows — compute_feature_frame must fill these, matching
        # BrainTradingEnv's own zero-padding convention.
        df = _synthetic_ohlcv()
        features = compute_feature_frame(df)
        assert not features.isna().any().any()
        assert np.isfinite(features.to_numpy()).all()

    def test_missing_columns_raises_clear_error(self):
        df = pd.DataFrame({"open": [1, 2], "high": [1, 2], "low": [1, 2]})  # no close/volume
        with pytest.raises(ValueError, match="missing columns"):
            compute_feature_frame(df)

    def test_zero_division_does_not_produce_inf(self):
        # A flat/zero-volume series would divide-by-zero in several
        # features (volume_ratio, price_position, bb_position, ...) —
        # confirm the .replace(0, nan).fillna(0.0) guards actually hold.
        n = 50
        flat = pd.DataFrame({
            "open": [100.0] * n, "high": [100.0] * n, "low": [100.0] * n,
            "close": [100.0] * n, "volume": [0.0] * n,
        })
        features = compute_feature_frame(flat)
        assert np.isfinite(features.to_numpy()).all()


class TestRLDataPipelineAdapterContract:
    """Verifies the exact 5-method contract BrainTradingEnv requires —
    see ml/extensions/rl/env.py's reset()/step()/_get_observation()."""

    def test_get_features_shape_matches_window(self):
        adapter = RLDataPipelineAdapter(_synthetic_ohlcv(200), start_index=100)
        obs = adapter.get_features(window=50)
        assert obs.shape == (50, 20)
        assert obs.dtype == np.float32

    def test_get_features_pads_when_insufficient_history(self):
        # start_index=5 with window=50 means only 6 real rows exist —
        # the rest must be zero-padded at the front, same as
        # example.py's MockDataPipeline.
        adapter = RLDataPipelineAdapter(_synthetic_ohlcv(200), start_index=5)
        obs = adapter.get_features(window=50)
        assert obs.shape == (50, 20)
        assert np.all(obs[:44] == 0.0)  # padded region

    def test_reset_returns_to_start_index(self):
        adapter = RLDataPipelineAdapter(_synthetic_ohlcv(200), start_index=20)
        adapter.step()
        adapter.step()
        adapter.reset()
        assert adapter.get_current_price() == pytest.approx(
            float(adapter._ohlcv["close"].iloc[20])
        )

    def test_step_advances_one_bar_and_clamps_at_end(self):
        df = _synthetic_ohlcv(10)
        adapter = RLDataPipelineAdapter(df, start_index=8)
        adapter.step()
        assert adapter.is_done()  # idx=9, len=10 → last bar
        adapter.step()  # must not raise/overrun
        assert adapter.get_current_price() == pytest.approx(float(df["close"].iloc[9]))

    def test_get_current_price_matches_close(self):
        df = _synthetic_ohlcv(50)
        adapter = RLDataPipelineAdapter(df, start_index=10)
        assert adapter.get_current_price() == pytest.approx(float(df["close"].iloc[10]))

    def test_is_done_false_until_last_bar(self):
        adapter = RLDataPipelineAdapter(_synthetic_ohlcv(50), start_index=0)
        assert not adapter.is_done()

    def test_empty_dataframe_raises(self):
        with pytest.raises(ValueError, match="empty"):
            RLDataPipelineAdapter(pd.DataFrame(columns=["open", "high", "low", "close", "volume"]))

    def test_get_online_features_returns_flat_scalar_dict(self):
        adapter = RLDataPipelineAdapter(_synthetic_ohlcv(100), start_index=50)
        online = adapter.get_online_features()
        assert set(online.keys()) == set(FEATURE_NAMES)
        assert all(isinstance(v, float) for v in online.values())


class TestFromProvider:
    def test_from_provider_calls_real_get_ohlcv_signature(self):
        class FakeProvider:
            def get_ohlcv(self, timeframe, limit=None, symbol=None):
                self.called_with = (timeframe, limit, symbol)
                return _synthetic_ohlcv(limit or 100)

        provider = FakeProvider()
        adapter = RLDataPipelineAdapter.from_provider(
            provider, timeframe="15m", limit=300, symbol="BTCUSDT"
        )
        assert provider.called_with == ("15m", 300, "BTCUSDT")
        assert isinstance(adapter, RLDataPipelineAdapter)
