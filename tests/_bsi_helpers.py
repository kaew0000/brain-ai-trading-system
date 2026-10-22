"""Shared helpers for the test_bsi_* modules. EVERYTHING generated here is SYNTHETIC test data - not market data."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from brain_strategy_intelligence.config import Config, load_config
from brain_strategy_intelligence.evaluation.data import SyntheticDataAdapter
from brain_strategy_intelligence.knowledge.repository import KnowledgeRepository
from brain_strategy_intelligence.knowledge.sqlite_store import SQLiteStrategyStore
from brain_strategy_intelligence.schemas import (
    Candle,
    Metrics,
    Provenance,
    StrategyCategory,
    StrategyDefinition,
    TradeRecord,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def make_strategy(sid: str = "s-one", **kw) -> StrategyDefinition:
    base = dict(
        id=sid,
        name="Test strategy",
        category=StrategyCategory.TREND_FOLLOWING,
        description="synthetic test strategy trend",
        engine="sma_cross",
        parameters={"fast": 10, "slow": 40},
        market_conditions=["TREND"],
        provenance=Provenance(source="tests"),
    )
    base.update(kw)
    return StrategyDefinition(**base)


def small_cfg(**ev) -> Config:
    over = {
        "evaluation": {
            "min_bars": 300,
            "min_oos_trades": 1,
            "walk_forward": {"train_bars": 100, "test_bars": 50, "step_bars": 50, "purge_bars": 3},
            **ev,
        }
    }
    return load_config(env={}, overrides=over)


def synthetic_candles(n: int = 1500, seed: int = 11) -> list[Candle]:
    return SyntheticDataAdapter(n=n, seed=seed).get_candles()


def flat_candles(closes: list[float], bar_seconds: int = 28800) -> list[Candle]:
    """open == high == low == close for every bar (hand-checkable arithmetic)."""
    return [Candle(ts=1_700_000_000 + i * bar_seconds, open=c, high=c, low=c, close=c) for i, c in enumerate(closes)]


def mk_metrics(**kw) -> Metrics:
    base = dict(
        net_pnl=500.0,
        return_pct=5.0,
        max_drawdown_pct=5.0,
        profit_factor=1.8,
        win_rate=0.5,
        expectancy=5.0,
        trade_count=100,
        avg_win=20.0,
        avg_loss=-10.0,
        payoff_ratio=2.0,
        exposure=0.4,
        turnover=10.0,
        benchmark_return_pct=1.0,
        fees_paid=20.0,
        slippage_cost=10.0,
        funding_paid=5.0,
        return_over_drawdown=1.0,
        sharpe=1.0,
        bars=1000,
    )
    base.update(kw)
    return Metrics(**base)


def mk_trade(tid: str = "t1", **kw) -> TradeRecord:
    base = dict(
        trade_id=tid,
        strategy_id="s-one",
        strategy_version=1,
        symbol="SYNUSDT",
        timeframe="15m",
        regime="TREND",
        direction="LONG",
        status="CLOSED",
        verified=True,
        entry_time=T0,
        exit_time=T0 + timedelta(hours=1),
        entry_price=100.0,
        exit_price=101.0,
        quantity=1.0,
        fees=0.1,
        funding=0.0,
        realized_pnl=1.0,
    )
    base.update(kw)
    return TradeRecord(**base)


@pytest.fixture(name="repo")
def repo_fixture():
    r = KnowledgeRepository(SQLiteStrategyStore(":memory:"))
    yield r
    r.store.close()


@pytest.fixture(name="cfg")
def cfg_fixture() -> Config:
    return small_cfg()
