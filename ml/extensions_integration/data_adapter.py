"""
RLDataPipelineAdapter — the real `data_pipeline` object
ml/extensions/rl/env.py's BrainTradingEnv (PR #82) expects.

BrainTradingEnv is not fed Brain Bot's production data layer directly —
it requires an object exposing exactly five methods. Confirmed by
reading ml/extensions/rl/env.py's BrainTradingEnv.__init__/reset/step
and its own ml/extensions/example.py's MockDataPipeline:

    get_features(window: int) -> np.ndarray   shape (window, 20)
    reset() -> None
    step() -> None
    get_current_price() -> float
    is_done() -> bool

(`n_features = 20` is hardcoded inside BrainTradingEnv.__init__ — see
that file's own "# Adjust based on your feature engineering" comment.
This adapter's feature matrix is therefore fixed at exactly 20 columns
to match it, without editing ml/extensions/ itself — this integration
layer is additive-only.)

This adapter implements that contract over REAL OHLCV data, sourced
from data/binance_provider.py's BinanceDataProvider.get_ohlcv() — the
one real, confirmed method on that class. A single historical batch is
fetched once (see from_provider()) and then walked in-memory
index-by-index, the same approach ml/extensions/example.py's own
MockDataPipeline uses — not a live exchange call on every step(), which
would be both rate-limit-hostile and non-reproducible for training.

Feature engineering below is plain pandas technical-indicator math with
no dependency on any other Brain Bot subsystem, so it is fully unit
testable with a synthetic DataFrame and no live exchange connection.
"""
from __future__ import annotations

import logging
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# BrainTradingEnv hardcodes n_features=20 — keep this list's length in
# sync with that constant if either is ever deliberately changed.
FEATURE_NAMES: list[str] = [
    "returns_1", "returns_5", "returns_10", "returns_20",
    "log_returns_1",
    "volatility_5", "volatility_10", "volatility_20",
    "volume_ratio_10", "volume_ratio_20",
    "price_position_20", "high_low_range_pct", "close_open_range_pct",
    "rsi_14", "rsi_7",
    "macd", "macd_signal", "macd_hist",
    "bb_position_20",
    "atr_pct_14",
]
assert len(FEATURE_NAMES) == 20, "BrainTradingEnv hardcodes n_features=20 — keep in sync"

_REQUIRED_COLUMNS = {"open", "high", "low", "close", "volume"}


def _rsi(prices: pd.Series, period: int) -> pd.Series:
    delta = prices.diff()
    gain = delta.where(delta > 0, 0.0).rolling(period).mean()
    loss = (-delta.where(delta < 0, 0.0)).rolling(period).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_feature_frame(ohlcv: pd.DataFrame) -> pd.DataFrame:
    """
    Pure function: OHLCV (open/high/low/close/volume columns) -> a
    DataFrame with exactly FEATURE_NAMES columns and the same row count
    as the input. NaN (from warm-up windows) is filled with 0.0,
    matching BrainTradingEnv's own zero-padding convention for
    insufficient history.
    """
    missing = _REQUIRED_COLUMNS - set(ohlcv.columns)
    if missing:
        raise ValueError(f"compute_feature_frame: OHLCV missing columns {sorted(missing)}")

    close = ohlcv["close"]
    high = ohlcv["high"]
    low = ohlcv["low"]
    volume = ohlcv["volume"]

    f = pd.DataFrame(index=ohlcv.index)
    f["returns_1"] = close.pct_change(1)
    f["returns_5"] = close.pct_change(5)
    f["returns_10"] = close.pct_change(10)
    f["returns_20"] = close.pct_change(20)
    f["log_returns_1"] = np.log(close / close.shift(1))

    f["volatility_5"] = f["returns_1"].rolling(5).std()
    f["volatility_10"] = f["returns_1"].rolling(10).std()
    f["volatility_20"] = f["returns_1"].rolling(20).std()

    vol_ma_10 = volume.rolling(10).mean()
    vol_ma_20 = volume.rolling(20).mean()
    f["volume_ratio_10"] = volume / vol_ma_10.replace(0, np.nan)
    f["volume_ratio_20"] = volume / vol_ma_20.replace(0, np.nan)

    roll_low_20 = low.rolling(20).min()
    roll_high_20 = high.rolling(20).max()
    rng_20 = (roll_high_20 - roll_low_20).replace(0, np.nan)
    f["price_position_20"] = (close - roll_low_20) / rng_20

    f["high_low_range_pct"] = (high - low) / close.replace(0, np.nan)
    f["close_open_range_pct"] = (close - ohlcv["open"]) / ohlcv["open"].replace(0, np.nan)

    f["rsi_14"] = _rsi(close, 14)
    f["rsi_7"] = _rsi(close, 7)

    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    f["macd"] = macd
    f["macd_signal"] = macd_signal
    f["macd_hist"] = macd - macd_signal

    bb_ma = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = bb_ma + 2 * bb_std
    bb_lower = bb_ma - 2 * bb_std
    bb_rng = (bb_upper - bb_lower).replace(0, np.nan)
    f["bb_position_20"] = (close - bb_lower) / bb_rng

    prev_close = close.shift(1)
    true_range = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr_14 = true_range.rolling(14).mean()
    f["atr_pct_14"] = atr_14 / close.replace(0, np.nan)

    f = f[FEATURE_NAMES]
    return f.replace([np.inf, -np.inf], np.nan).fillna(0.0)


class RLDataPipelineAdapter:
    """
    Implements the exact data_pipeline contract BrainTradingEnv requires
    (get_features/reset/step/get_current_price/is_done), backed by a
    pre-loaded historical OHLCV DataFrame walked index-by-index.

    Also exposes get_online_features(), a flat scalar dict of the same
    20 features at the current step, for
    ml.extensions.online.learner.OnlineLearner/MultiSymbolOnlineLearner
    (River), which take Dict[str, float] rather than an array.
    """

    def __init__(self, ohlcv: pd.DataFrame, start_index: Optional[int] = None) -> None:
        if len(ohlcv) == 0:
            raise ValueError("RLDataPipelineAdapter: ohlcv is empty")

        missing = _REQUIRED_COLUMNS - set(ohlcv.columns)
        if missing:
            raise ValueError(f"RLDataPipelineAdapter: OHLCV missing columns {sorted(missing)}")

        self._ohlcv = ohlcv.reset_index(drop=True)
        self._features = compute_feature_frame(self._ohlcv)
        self._start_index = self._clip(start_index if start_index is not None else 0)
        self._idx = self._start_index
        logger.info(f"RLDataPipelineAdapter initialized: {len(self._ohlcv)} bars")

    def _clip(self, idx: int) -> int:
        return max(0, min(idx, len(self._ohlcv) - 1))

    @classmethod
    def from_provider(
        cls,
        data_provider,
        timeframe: str,
        limit: int,
        symbol: Optional[str] = None,
    ) -> "RLDataPipelineAdapter":
        """
        Fetches ONE historical OHLCV batch via the real
        BinanceDataProvider.get_ohlcv(timeframe, limit, symbol)
        (data/binance_provider.py) and wraps it. Network/exchange
        errors propagate to the caller — this classmethod does not
        swallow them, since a caller explicitly requesting live data
        should know if the fetch failed rather than silently getting an
        empty adapter.
        """
        df = data_provider.get_ohlcv(timeframe, limit=limit, symbol=symbol)
        return cls(df)

    # ── BrainTradingEnv's required data_pipeline contract ────────────
    def get_features(self, window: int = 50) -> np.ndarray:
        end = self._idx + 1
        start = max(0, end - window)
        chunk = self._features.iloc[start:end].to_numpy(dtype=np.float32)
        if chunk.shape[0] < window:
            pad = np.zeros((window - chunk.shape[0], len(FEATURE_NAMES)), dtype=np.float32)
            chunk = np.vstack([pad, chunk])
        return chunk

    def reset(self) -> None:
        self._idx = self._start_index

    def step(self) -> None:
        self._idx = min(self._idx + 1, len(self._ohlcv) - 1)

    def get_current_price(self) -> float:
        return float(self._ohlcv["close"].iloc[self._idx])

    def is_done(self) -> bool:
        return self._idx >= len(self._ohlcv) - 1

    # ── Online learner (River) features ──────────────────────────────
    def get_online_features(self) -> dict:
        """Flat scalar feature dict at the current step, for
        OnlineLearner.learn()/predict() — same 20 features as
        get_features(), just the current row as a named dict."""
        row = self._features.iloc[self._idx]
        return {name: float(row[name]) for name in FEATURE_NAMES}
