"""Event-driven single-asset backtester.

No-look-ahead design:
* signals are computed at a bar's CLOSE from a window that ends at that bar;
* the order is filled at the NEXT bar's OPEN, with adverse slippage;
* stops are checked intrabar using that bar's low/high; a gap through the stop fills at the (worse) open;
* parameters are never tuned on data after the evaluated segment (see walk_forward.py);
* only candles[:trade_end] are ever read.
Liquidation is not modelled; leverage is capped by config (document in evaluation assumptions).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ..config import EvaluationCfg
from ..schemas import Candle, Metrics
from .costs import CostModel
from .engines import Engine, Params


@dataclass
class Trade:
    entry_idx: int
    exit_idx: int
    direction: int
    entry_price: float
    exit_price: float
    qty: float
    gross_pnl: float
    fees: float
    funding: float
    slippage_cost: float
    net_pnl: float
    exit_reason: str


@dataclass
class BacktestResult:
    trades: list[Trade] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)  # mark-to-market, one point per traded bar
    bars: int = 0
    bars_in_position: int = 0
    notional_traded: float = 0.0
    bankrupt: bool = False
    initial_capital: float = 0.0
    first_open: float = 0.0
    last_close: float = 0.0


def run_backtest(
    candles: list[Candle],
    engine: Engine,
    params: Params,
    cfg: EvaluationCfg,
    *,
    bar_seconds: int,
    trade_start: int = 0,
    trade_end: int | None = None,
) -> BacktestResult:
    n = len(candles) if trade_end is None else min(trade_end, len(candles))
    engine.validate(params)
    hist = engine.history(params)
    cost = CostModel.from_config(cfg)
    res = BacktestResult(initial_capital=cfg.initial_capital)
    if trade_start >= n:
        return res
    res.first_open, res.last_close = candles[trade_start].open, candles[n - 1].close
    equity = cfg.initial_capital
    pos, entry_px, qty, entry_idx = 0, 0.0, 0.0, 0
    entry_fee = funding_acc = slip_acc = entry_notional = 0.0

    def close_pos(idx: int, raw_price: float, reason: str) -> None:
        nonlocal equity, pos, qty, entry_fee, funding_acc, slip_acc
        fill = cost.fill_price(raw_price, -pos)
        gross = pos * (fill - entry_px) * qty
        exit_fee = cost.fee(fill * qty)
        slip = slip_acc + abs(fill - raw_price) * qty
        fees = entry_fee + exit_fee
        net = gross - fees - funding_acc
        equity += net
        res.notional_traded += fill * qty
        res.trades.append(Trade(entry_idx, idx, pos, entry_px, fill, qty, gross, fees, funding_acc, slip, net, reason))
        pos, qty, entry_fee, funding_acc, slip_acc = 0, 0.0, 0.0, 0.0, 0.0

    pending: int | None = None
    if trade_start >= hist:  # decision made at the close of the bar BEFORE trade_start
        t = engine.fn(candles[trade_start - hist : trade_start], params, 0)
        pending = t if cfg.allow_short else max(t, 0)

    for i in range(trade_start, n):
        c = candles[i]
        if pending is not None and pending != pos:
            if pos != 0:
                close_pos(i, c.open, "signal")
            if pending != 0 and equity > 0:
                fill = cost.fill_price(c.open, pending)
                entry_notional = equity * min(cfg.position_pct, cfg.max_leverage)
                qty = entry_notional / fill
                entry_fee = cost.fee(entry_notional)
                slip_acc = abs(fill - c.open) * qty
                pos, entry_px, entry_idx, funding_acc = pending, fill, i, 0.0
                res.notional_traded += entry_notional
        pending = None
        if pos != 0 and cfg.stop_loss_pct:
            stop = entry_px * (1 - pos * cfg.stop_loss_pct)
            hit = c.low <= stop if pos > 0 else c.high >= stop
            if hit:
                gap = c.open <= stop if pos > 0 else c.open >= stop
                close_pos(i, c.open if gap else stop, "stop_gap" if gap else "stop")
        if pos != 0:
            funding_acc += cost.funding_cost(entry_notional, pos, bar_seconds)
            res.bars_in_position += 1
        mtm = equity + (pos * (c.close - entry_px) * qty - entry_fee - funding_acc if pos else 0.0)
        res.equity.append(mtm)
        res.bars += 1
        if mtm <= 0:
            res.bankrupt = True
            if pos != 0:
                close_pos(i, c.close, "bankrupt")
                res.equity[-1] = equity
            break
        if i < n - 1 and i + 1 >= hist:
            t = engine.fn(candles[i + 1 - hist : i + 1], params, pos)
            t = t if cfg.allow_short else max(t, 0)
            pending = t if t != pos else None

    if pos != 0:
        close_pos(n - 1, candles[n - 1].close, "end_of_data")
        res.equity[-1] = equity
    return res


def compute_metrics(res: BacktestResult, bar_seconds: int) -> Metrics:
    ic = res.initial_capital
    final = res.equity[-1] if res.equity else ic
    peak, mdd = ic, 0.0
    for e in res.equity:
        peak = max(peak, e)
        mdd = max(mdd, (peak - e) / peak * 100.0 if peak > 0 else 0.0)
    net = final - ic
    nets = [t.net_pnl for t in res.trades]
    wins = [x for x in nets if x > 0]
    losses = [x for x in nets if x < 0]
    pf = (sum(wins) / -sum(losses)) if losses and wins else None
    ret = net / ic * 100.0
    sharpe = None
    if len(res.equity) >= 30:
        series = [ic, *res.equity]
        rets = [series[i] / series[i - 1] - 1.0 for i in range(1, len(series)) if series[i - 1] > 0]
        if len(rets) >= 30:
            m = sum(rets) / len(rets)
            sd = math.sqrt(sum((r - m) ** 2 for r in rets) / (len(rets) - 1))
            if sd > 0:
                sharpe = m / sd * math.sqrt(365 * 86400 / bar_seconds)
    avg_win = sum(wins) / len(wins) if wins else None
    avg_loss = sum(losses) / len(losses) if losses else None
    return Metrics(
        net_pnl=net,
        return_pct=ret,
        max_drawdown_pct=mdd,
        profit_factor=pf,
        win_rate=(len(wins) / len(nets)) if nets else None,
        expectancy=(sum(nets) / len(nets)) if nets else None,
        trade_count=len(nets),
        avg_win=avg_win,
        avg_loss=avg_loss,
        payoff_ratio=(avg_win / -avg_loss) if avg_win and avg_loss else None,
        exposure=(res.bars_in_position / res.bars) if res.bars else 0.0,
        turnover=res.notional_traded / ic,
        benchmark_return_pct=((res.last_close / res.first_open - 1.0) * 100.0) if res.first_open else 0.0,
        fees_paid=sum(t.fees for t in res.trades),
        slippage_cost=sum(t.slippage_cost for t in res.trades),
        funding_paid=sum(t.funding for t in res.trades),
        return_over_drawdown=(ret / mdd) if mdd > 0 else None,
        sharpe=sharpe,
        bars=res.bars,
    )
