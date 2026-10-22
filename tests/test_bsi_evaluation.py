"""Backtest arithmetic, costs, look-ahead prevention, walk-forward separation, missing data. (SYNTHETIC data only.)"""

import random

import pytest
from tests._bsi_helpers import flat_candles, make_strategy, small_cfg, synthetic_candles

from brain_strategy_intelligence.config import SplitCfg, WalkForwardCfg, load_config
from brain_strategy_intelligence.errors import DataError
from brain_strategy_intelligence.evaluation.backtester import compute_metrics, run_backtest
from brain_strategy_intelligence.evaluation.data import CSVDataAdapter, SyntheticDataAdapter
from brain_strategy_intelligence.evaluation.engines import ENGINES, Engine, get_engine
from brain_strategy_intelligence.evaluation.evaluator import StrategyEvaluator
from brain_strategy_intelligence.evaluation.walk_forward import (
    parameter_sensitivity,
    run_walk_forward,
    split_indices,
    walk_forward_windows,
)
from brain_strategy_intelligence.schemas import Candle

from tests._bsi_helpers import cfg_fixture  # noqa: F401  (fixtures)

pytestmark = pytest.mark.unit

BAR = 28800  # 8h bars so one bar == one funding interval


def threshold_engine() -> Engine:
    """Test-only engine: enter long when 110<=close<=115, stay long while close>=120, else flat."""

    def fn(w, p, pos):
        c = w[-1].close
        return 1 if (pos == 0 and 110 <= c <= 115) or (pos == 1 and c >= 120) else 0

    return Engine("thr", fn, lambda p: 1, lambda p: None)


CLOSES = [100, 100, 110, 120, 130, 125, 119, 124, 124]


def cfg_with(**ev):
    base = dict(fee_bps=0.0, slippage_bps=0.0, include_funding=False, position_pct=0.1)
    base.update(ev)
    return load_config(env={}, overrides={"evaluation": base}).evaluation


def test_hand_checked_pnl_without_costs():
    res = run_backtest(flat_candles(CLOSES), threshold_engine(), {}, cfg_with(), bar_seconds=BAR)
    t = res.trades[0]
    qty = 1000 / 120  # signal at close idx2 -> fill at OPEN of idx3 (120); notional = 10% of 10000
    assert (
        len(res.trades) == 1 and t.entry_price == 120 and t.exit_price == 124 and t.entry_idx == 3 and t.exit_idx == 7
    )
    assert t.net_pnl == pytest.approx(qty * 4)
    m = compute_metrics(res, BAR)
    assert m.net_pnl == pytest.approx(qty * 4) and m.trade_count == 1 and m.win_rate == 1.0
    assert m.profit_factor is None  # no losing trades -> undefined, not infinite/perfect


def test_fees_slippage_and_funding_reduce_pnl_exactly():
    c = flat_candles(CLOSES)
    fees = run_backtest(c, threshold_engine(), {}, cfg_with(fee_bps=10), bar_seconds=BAR).trades[0]
    qty = 1000 / 120
    assert fees.fees == pytest.approx(1000 * 10 / 1e4 + 124 * qty * 10 / 1e4)
    assert fees.net_pnl == pytest.approx(qty * 4 - fees.fees)
    slip = run_backtest(c, threshold_engine(), {}, cfg_with(slippage_bps=100), bar_seconds=BAR).trades[0]
    assert slip.entry_price == pytest.approx(120 * 1.01) and slip.exit_price == pytest.approx(124 * 0.99)
    fund = run_backtest(
        c, threshold_engine(), {}, cfg_with(include_funding=True, funding_rate_per_8h=0.001), bar_seconds=BAR
    ).trades[0]
    assert fund.funding == pytest.approx(4 * 0.001 * 1000)  # held through idx3..idx6 = 4 funding intervals
    base = run_backtest(c, threshold_engine(), {}, cfg_with(), bar_seconds=BAR).trades[0]
    assert fund.net_pnl < base.net_pnl and slip.net_pnl < base.net_pnl


def test_stop_gap_fills_at_worse_open_not_at_stop():
    closes = [100, 100, 110, 120, 100, 100, 100]
    res = run_backtest(flat_candles(closes), threshold_engine(), {}, cfg_with(stop_loss_pct=0.05), bar_seconds=BAR)
    t = res.trades[0]
    assert t.exit_reason == "stop_gap" and t.exit_price == 100  # stop was 114 but price gapped to 100


def test_open_position_is_force_closed_at_end_of_data():
    res = run_backtest(
        flat_candles([100, 100, 110, 120, 130, 130]), threshold_engine(), {}, cfg_with(), bar_seconds=BAR
    )
    assert res.trades[-1].exit_reason == "end_of_data" and res.trades[-1].exit_idx == 5


def test_no_lookahead_future_changes_do_not_alter_past_equity():
    candles = synthetic_candles(1200, seed=3)
    cfg = small_cfg().evaluation
    eng = get_engine("sma_cross")
    params = {"fast": 10, "slow": 40}
    base = run_backtest(candles, eng, params, cfg, bar_seconds=900)
    k = 800
    rng = random.Random(1)
    mutated = candles[:k] + [
        Candle(ts=c.ts, open=(p := rng.uniform(10, 500)), high=p * 1.01, low=p * 0.99, close=p) for c in candles[k:]
    ]
    alt = run_backtest(mutated, eng, params, cfg, bar_seconds=900)
    assert base.equity[:k] == alt.equity[:k]  # everything up to bar k-1 is independent of the future


def test_signal_fills_at_next_open_never_at_signal_bar_price():
    c = flat_candles(CLOSES)
    t = run_backtest(c, threshold_engine(), {}, cfg_with(), bar_seconds=BAR).trades[0]
    assert t.entry_idx == 3 and t.entry_price == c[3].open != c[2].close


def test_splits_are_contiguous_ordered_and_non_overlapping():
    a, b = split_indices(1000, SplitCfg(train=0.6, validation=0.2, oos=0.2))
    assert (a, b) == (600, 800) and 0 < a < b < 1000


def test_walk_forward_windows_have_no_overlap_and_respect_purge():
    wf = WalkForwardCfg(train_bars=100, test_bars=50, step_bars=50, purge_bars=5)
    wins = walk_forward_windows(500, wf)
    assert wins
    for tr, te in wins:
        assert tr[1] <= te[0] and te[0] - tr[1] == 5 and te[1] <= 500 and tr[0] < tr[1] and te[0] < te[1]


def test_walk_forward_parameter_choice_ignores_test_data():
    cfg = small_cfg().evaluation
    s = make_strategy("wf-1", param_grid={"fast": [5, 10, 20]})
    eng = get_engine("sma_cross")
    candles = synthetic_candles(1200, seed=5)
    base, _ = run_walk_forward(candles, s, eng, cfg, 900)
    w0 = base.windows[0]
    lo = w0.test_range[0]
    rng = random.Random(9)
    mutated = candles[:lo] + [
        Candle(ts=c.ts, open=(p := rng.uniform(10, 500)), high=p * 1.01, low=p * 0.99, close=p) for c in candles[lo:]
    ]
    alt, _ = run_walk_forward(mutated, s, eng, cfg, 900)
    assert alt.windows[0].chosen_params == w0.chosen_params and alt.windows[0].train_net_pnl == w0.train_net_pnl


def test_sensitivity_uses_neighbours_and_reports_fraction():
    cfg = small_cfg().evaluation
    r = parameter_sensitivity(
        synthetic_candles(1200), make_strategy("sens"), get_engine("sma_cross"), cfg, 900, 600, 900
    )
    assert r is not None and len(r.neighbours) >= 2 and 0.0 <= r.positive_neighbour_fraction <= 1.0


def test_full_evaluation_is_complete_deterministic_and_labelled(cfg):
    ev1 = StrategyEvaluator(cfg).evaluate(
        make_strategy("e1"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    ev2 = StrategyEvaluator(cfg).evaluate(
        make_strategy("e1"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    assert ev1.status == "COMPLETE" and ev1.evaluation_id == ev2.evaluation_id
    assert ev1.in_sample and ev1.validation and ev1.out_of_sample and ev1.walk_forward and ev1.assumptions
    assert any("SYNTHETIC" in w for w in ev1.warnings)


def test_insufficient_history_is_incomplete_with_no_metrics(cfg):
    ev = StrategyEvaluator(cfg).evaluate(
        make_strategy("e2"), synthetic_candles(120), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    assert ev.status == "INCOMPLETE" and ev.in_sample is None and ev.out_of_sample is None
    assert "insufficient history" in ev.incomplete_reasons[0]


def test_knowledge_only_strategy_cannot_be_evaluated(cfg):
    s = make_strategy("smc-1", engine=None, parameters={}, category="smart_money_concepts")
    ev = StrategyEvaluator(cfg).evaluate(
        s, synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    assert ev.status == "INCOMPLETE" and "no executable engine" in ev.incomplete_reasons[0]


def test_too_few_oos_trades_marks_incomplete():
    cfg = small_cfg(min_oos_trades=10_000)
    ev = StrategyEvaluator(cfg).evaluate(
        make_strategy("e3"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)"
    )
    assert ev.status == "INCOMPLETE" and any("out-of-sample trades" in r for r in ev.incomplete_reasons)
    assert ev.out_of_sample is not None  # real numbers are shown, but the result is flagged incomplete


def test_unordered_duplicate_or_gappy_data_is_rejected(cfg):
    c = synthetic_candles(500)
    dup = [*c[:100], c[100], c[100], *c[101:]]
    ev = StrategyEvaluator(cfg).evaluate(make_strategy("e4"), dup, symbol="SYNUSDT", timeframe="15m", data_label="x")
    assert ev.status == "INCOMPLETE" and "strictly increasing" in ev.incomplete_reasons[0]
    gappy = [x for i, x in enumerate(c) if i % 10 < 8]  # drop 2 consecutive bars out of every 10
    ev2 = StrategyEvaluator(cfg).evaluate(make_strategy("e5"), gappy, symbol="SYNUSDT", timeframe="15m", data_label="x")
    assert ev2.status == "INCOMPLETE" and "gaps" in ev2.incomplete_reasons[0]


def test_invalid_parameters_and_unknown_engine_are_incomplete(cfg):
    ev = StrategyEvaluator(cfg).evaluate(
        make_strategy("e6", parameters={"fast": 50, "slow": 10}),
        synthetic_candles(),
        symbol="SYNUSDT",
        timeframe="15m",
        data_label="x",
    )
    assert ev.status == "INCOMPLETE" and "invalid parameters" in ev.incomplete_reasons[0]
    ev2 = StrategyEvaluator(cfg).evaluate(
        make_strategy("e7", engine="does_not_exist"),
        synthetic_candles(),
        symbol="SYNUSDT",
        timeframe="15m",
        data_label="x",
    )
    assert ev2.status == "INCOMPLETE"


def test_higher_costs_never_improve_results(cfg):
    lo = StrategyEvaluator(small_cfg(fee_bps=0, slippage_bps=0, include_funding=False))
    hi = StrategyEvaluator(small_cfg(fee_bps=20, slippage_bps=20))
    args = dict(symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(t)")
    a = lo.evaluate(make_strategy("c1"), synthetic_candles(), **args).out_of_sample
    b = hi.evaluate(make_strategy("c1"), synthetic_candles(), **args).out_of_sample
    assert b.net_pnl < a.net_pnl and b.fees_paid > a.fees_paid


def test_every_builtin_engine_runs_on_synthetic_data():
    cfg = small_cfg().evaluation
    params = {
        "sma_cross": {"fast": 10, "slow": 40},
        "donchian_breakout": {"entry_lookback": 30, "exit_lookback": 10},
        "rsi_reversion": {"period": 14, "oversold": 30, "overbought": 70},
        "roc_momentum": {"lookback": 24, "threshold_pct": 2.0},
        "bb_squeeze_breakout": {"period": 20, "num_std": 2.0, "squeeze_bandwidth_pct": 4.0},
        "mtf_confluence": {"fast": 10, "slow": 30, "htf_factor": 4},
    }
    assert set(params) == set(ENGINES)
    c = synthetic_candles(1000)
    for name, p in params.items():
        res = run_backtest(c, ENGINES[name], p, cfg, bar_seconds=900)
        assert res.bars == 1000 and compute_metrics(res, 900).trade_count >= 0


def test_csv_adapter_fails_closed_on_bad_input(tmp_path):
    good = tmp_path / "g.csv"
    good.write_text("ts,open,high,low,close,volume\n1700000000,10,11,9,10.5,5\n1700000900,10.5,11,10,10.8,6\n")
    assert len(CSVDataAdapter(good).get_candles()) == 2
    bad = tmp_path / "b.csv"
    bad.write_text("ts,open,high,low,close\n1700000000,10,9,11,10.5\n")  # high < low
    with pytest.raises(DataError):
        CSVDataAdapter(bad).get_candles()
    nocols = tmp_path / "n.csv"
    nocols.write_text("a,b\n1,2\n")
    with pytest.raises(DataError):
        CSVDataAdapter(nocols).get_candles()
    with pytest.raises(DataError):
        CSVDataAdapter(tmp_path / "missing.csv").get_candles()


def test_synthetic_adapter_is_deterministic_and_labelled():
    a, b = SyntheticDataAdapter(500, 1), SyntheticDataAdapter(500, 1)
    assert a.get_candles() == b.get_candles() and a.label.startswith("SYNTHETIC")
