"""Thin convenience wrappers so callers can import metrics from a stable module path."""

from __future__ import annotations

from ..config import EvaluationCfg
from ..schemas import Candle, Metrics
from .backtester import compute_metrics, run_backtest
from .engines import Engine, Params


def segment_metrics(
    candles: list[Candle], engine: Engine, params: Params, cfg: EvaluationCfg, *, bar_seconds: int, start: int, end: int
) -> Metrics:
    """Backtest [start, end) using earlier bars only as indicator warm-up (past data, never future)."""
    return compute_metrics(
        run_backtest(candles, engine, params, cfg, bar_seconds=bar_seconds, trade_start=start, trade_end=end),
        bar_seconds,
    )


__all__ = ["compute_metrics", "segment_metrics"]
