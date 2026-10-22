"""Chronological splits, walk-forward evaluation, and parameter-sensitivity analysis.

Data-separation guarantees (all asserted by tests):
* train < validation < out-of-sample, contiguous and non-overlapping;
* in every walk-forward window, test_start >= train_end + purge_bars (no overlap, no shared bars);
* parameters are chosen using the TRAIN range only; the TEST range is evaluated once with the frozen choice.
"""

from __future__ import annotations

import itertools

from ..config import EvaluationCfg, SplitCfg, WalkForwardCfg
from ..schemas import Candle, SensitivityResult, StrategyDefinition, WalkForwardSummary, WalkForwardWindow
from .backtester import compute_metrics, run_backtest
from .engines import Engine


def split_indices(n: int, split: SplitCfg) -> tuple[int, int]:
    """Return (a, b): train=[0,a), validation=[a,b), out_of_sample=[b,n)."""
    a = int(n * split.train)
    b = a + int(n * split.validation)
    return a, b


def walk_forward_windows(n: int, wf: WalkForwardCfg) -> list[tuple[tuple[int, int], tuple[int, int]]]:
    out = []
    start = 0
    while start + wf.train_bars + wf.purge_bars + wf.test_bars <= n:
        tr = (start, start + wf.train_bars)
        te = (tr[1] + wf.purge_bars, tr[1] + wf.purge_bars + wf.test_bars)
        out.append((tr, te))
        start += wf.step_bars
    return out


def _param_combos(strategy: StrategyDefinition, engine: Engine) -> list[dict]:
    base = dict(strategy.parameters)
    combos = [base]
    if strategy.param_grid:
        keys = sorted(strategy.param_grid)
        combos = [
            {**base, **dict(zip(keys, vals, strict=True))}
            for vals in itertools.product(*(strategy.param_grid[k] for k in keys))
        ]
    valid = []
    for c in combos:
        try:
            engine.validate(c)
            valid.append(c)
        except ValueError:
            continue
    return valid


def run_walk_forward(
    candles: list[Candle], strategy: StrategyDefinition, engine: Engine, cfg: EvaluationCfg, bar_seconds: int
) -> tuple[WalkForwardSummary | None, list[str]]:
    notes: list[str] = []
    windows_idx = walk_forward_windows(len(candles), cfg.walk_forward)
    if not windows_idx:
        return None, ["not enough bars for even one walk-forward window"]
    combos = _param_combos(strategy, engine)
    if not combos:
        return None, ["no valid parameter combination"]
    out: list[WalkForwardWindow] = []
    for tr, te in windows_idx:
        best, best_score, best_net = None, -1e18, 0.0
        for params in combos:
            m = compute_metrics(
                run_backtest(candles, engine, params, cfg, bar_seconds=bar_seconds, trade_start=tr[0], trade_end=tr[1]),
                bar_seconds,
            )
            score = m.return_pct / max(m.max_drawdown_pct, 1.0)  # selection uses TRAIN data only
            if score > best_score:
                best, best_score, best_net = params, score, m.net_pnl
        assert best is not None
        tm = compute_metrics(
            run_backtest(candles, engine, best, cfg, bar_seconds=bar_seconds, trade_start=te[0], trade_end=te[1]),
            bar_seconds,
        )
        out.append(
            WalkForwardWindow(
                train_range=tr,
                test_range=te,
                chosen_params=best,
                train_net_pnl=best_net,
                test_net_pnl=tm.net_pnl,
                test_trades=tm.trade_count,
            )
        )
    prof = sum(1 for w in out if w.test_net_pnl > 0) / len(out)
    return WalkForwardSummary(
        windows=out,
        profitable_fraction=prof,
        total_test_net_pnl=sum(w.test_net_pnl for w in out),
        total_test_trades=sum(w.test_trades for w in out),
    ), notes


def parameter_sensitivity(
    candles: list[Candle],
    strategy: StrategyDefinition,
    engine: Engine,
    cfg: EvaluationCfg,
    bar_seconds: int,
    start: int,
    end: int,
) -> SensitivityResult | None:
    """Perturb each numeric parameter by +/- pct and re-run on [start, end) (the validation segment, never OOS)."""
    base_m = compute_metrics(
        run_backtest(
            candles, engine, strategy.parameters, cfg, bar_seconds=bar_seconds, trade_start=start, trade_end=end
        ),
        bar_seconds,
    )
    pct = cfg.sensitivity_perturbation_pct
    neighbours: list[dict] = []
    for k, v in strategy.parameters.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            continue
        for sign in (-1, 1):
            nv = v * (1 + sign * pct)
            if isinstance(v, int):
                nv = max(1, round(nv))
                if nv == v:
                    nv = max(1, v + sign)
                if nv == v:
                    continue
            cand = {**strategy.parameters, k: nv}
            try:
                engine.validate(cand)
            except ValueError:
                continue
            m = compute_metrics(
                run_backtest(candles, engine, cand, cfg, bar_seconds=bar_seconds, trade_start=start, trade_end=end),
                bar_seconds,
            )
            neighbours.append({"param": k, "value": nv, "net_pnl": m.net_pnl})
    if not neighbours:
        return None
    denom = max(abs(base_m.net_pnl), 0.01 * cfg.initial_capital)
    return SensitivityResult(
        base_net_pnl=base_m.net_pnl,
        neighbours=neighbours,
        positive_neighbour_fraction=sum(1 for x in neighbours if x["net_pnl"] > 0) / len(neighbours),
        max_relative_change=max(abs(x["net_pnl"] - base_m.net_pnl) for x in neighbours) / denom,
    )
