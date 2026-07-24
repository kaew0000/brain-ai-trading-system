"""
Forward Testing Framework

Evaluates live/paper trading performance and auto-generates reports every N trades.

Metrics tracked:
  Win Rate, Profit Factor, Sharpe, Sortino, Expectancy, Max Drawdown,
  Calmar Ratio, consecutive stats, regime breakdown
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger("forward_test.evaluator")


@dataclass
class ForwardTestReport:
    generated_at:     str   = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    total_trades:     int   = 0
    winning_trades:   int   = 0
    losing_trades:    int   = 0
    win_rate:         float = 0.0
    gross_profit:     float = 0.0
    gross_loss:       float = 0.0
    profit_factor:    float = 0.0
    net_pnl:          float = 0.0
    expectancy:       float = 0.0
    sharpe:           float = 0.0
    sortino:          float = 0.0
    max_drawdown:     float = 0.0
    max_drawdown_pct: float = 0.0
    calmar:           float = 0.0
    avg_win:          float = 0.0
    avg_loss:         float = 0.0
    avg_rr:           float = 0.0
    best_trade:       float = 0.0
    worst_trade:      float = 0.0
    max_consec_wins:  int   = 0
    max_consec_loss:  int   = 0
    regime_breakdown: dict  = field(default_factory=dict)
    grade:            str   = "—"
    verdict:          str   = ""

    def to_dict(self) -> dict:
        return {k: getattr(self, k) for k in self.__dataclass_fields__}

    def summary_line(self) -> str:
        return (f"{self.total_trades} trades | WR {self.win_rate:.1f}% | "
                f"PF {self.profit_factor:.2f} | Sharpe {self.sharpe:.2f} | "
                f"MaxDD {self.max_drawdown_pct:.1f}% | Grade: {self.grade}")


class ForwardTestEvaluator:
    """
    Computes performance metrics from a list of closed trade dicts.

    Each trade dict must have at minimum:
        pnl : float  (realised PnL in USDT)

    Optional fields enhance analysis:
        entry_price, exit_price, direction, regime, timestamp,
        confidence, score, quantity
    """

    AUTO_REPORT_EVERY = 50   # generate report every N trades

    def __init__(self, starting_balance: float = 10_000.0) -> None:
        self._balance = starting_balance
        self._last_report_count = 0
        self._last_report: ForwardTestReport | None = None

    def evaluate(self, trades: list[dict]) -> ForwardTestReport:
        if not trades:
            return ForwardTestReport()

        pnls = [float(t.get("pnl", t.get("realised_pnl", 0.0)) or 0.0) for t in trades]
        wins = [p for p in pnls if p > 0]
        loss = [p for p in pnls if p < 0]

        n       = len(pnls)
        n_wins  = len(wins)
        n_loss  = len(loss)
        net     = sum(pnls)
        g_win   = sum(wins)
        g_loss  = abs(sum(loss))

        win_rate  = n_wins / n * 100 if n else 0.0
        pf        = g_win / g_loss if g_loss > 0 else (999.0 if g_win > 0 else 0.0)
        avg_win   = g_win / n_wins if n_wins else 0.0
        avg_loss  = g_loss / n_loss if n_loss else 0.0
        avg_rr    = avg_win / avg_loss if avg_loss else 0.0
        expectancy = (win_rate / 100 * avg_win) - ((1 - win_rate / 100) * avg_loss)

        # ── Equity curve ──────────────────────────────────────────────────
        equity = [self._balance]
        for p in pnls:
            equity.append(equity[-1] + p)

        max_dd, max_dd_pct = self._max_drawdown(equity)

        # ── Sharpe / Sortino ──────────────────────────────────────────────
        sharpe  = self._sharpe(pnls)
        sortino = self._sortino(pnls)
        calmar  = abs(net / max_dd_pct) if max_dd_pct > 0 else 0.0

        # ── Streaks ───────────────────────────────────────────────────────
        mc_wins, mc_loss = self._streaks(pnls)

        # ── Regime breakdown ──────────────────────────────────────────────
        regime_bd: dict[str, dict] = {}
        for t in trades:
            reg = t.get("regime", "UNKNOWN") or "UNKNOWN"
            pnl = float(t.get("pnl", t.get("realised_pnl", 0.0)) or 0.0)
            if reg not in regime_bd:
                regime_bd[reg] = {"n": 0, "wins": 0, "pnl": 0.0}
            regime_bd[reg]["n"]    += 1
            regime_bd[reg]["pnl"]  += pnl
            if pnl > 0: regime_bd[reg]["wins"] += 1
        for reg, d in regime_bd.items():
            d["wr"] = round(d["wins"] / d["n"] * 100, 1) if d["n"] else 0.0

        # ── Grade ──────────────────────────────────────────────────────────
        grade, verdict = self._grade(win_rate, pf, sharpe, max_dd_pct)

        r = ForwardTestReport(
            total_trades     = n,
            winning_trades   = n_wins,
            losing_trades    = n_loss,
            win_rate         = round(win_rate, 2),
            gross_profit     = round(g_win, 2),
            gross_loss       = round(g_loss, 2),
            profit_factor    = round(pf, 3),
            net_pnl          = round(net, 2),
            expectancy       = round(expectancy, 2),
            sharpe           = round(sharpe, 3),
            sortino          = round(sortino, 3),
            max_drawdown     = round(max_dd, 2),
            max_drawdown_pct = round(max_dd_pct, 2),
            calmar           = round(calmar, 3),
            avg_win          = round(avg_win, 2),
            avg_loss         = round(avg_loss, 2),
            avg_rr           = round(avg_rr, 3),
            best_trade       = round(max(pnls), 2),
            worst_trade      = round(min(pnls), 2),
            max_consec_wins  = mc_wins,
            max_consec_loss  = mc_loss,
            regime_breakdown = regime_bd,
            grade            = grade,
            verdict          = verdict,
        )
        self._last_report = r
        return r

    def should_auto_report(self, trade_count: int) -> bool:
        """True if trade_count crossed an AUTO_REPORT_EVERY boundary."""
        if trade_count - self._last_report_count >= self.AUTO_REPORT_EVERY:
            self._last_report_count = (trade_count // self.AUTO_REPORT_EVERY) * self.AUTO_REPORT_EVERY
            return True
        return False

    @property
    def last_report(self) -> ForwardTestReport | None:
        return self._last_report

    # ── Maths ─────────────────────────────────────────────────────────────

    @staticmethod
    def _max_drawdown(equity: list[float]) -> tuple[float, float]:
        peak = equity[0]
        max_dd = 0.0
        for e in equity:
            peak = max(peak, e)
            dd = peak - e
            max_dd = max(max_dd, dd)
        max_dd_pct = max_dd / peak * 100 if peak > 0 else 0.0
        return max_dd, max_dd_pct

    @staticmethod
    def _sharpe(pnls: list[float], rf: float = 0.0) -> float:
        if len(pnls) < 2: return 0.0
        n   = len(pnls)
        mu  = sum(pnls) / n - rf
        var = sum((p - mu) ** 2 for p in pnls) / (n - 1)
        std = math.sqrt(var)
        return mu / std * math.sqrt(252) if std > 0 else 0.0

    @staticmethod
    def _sortino(pnls: list[float], rf: float = 0.0) -> float:
        if len(pnls) < 2: return 0.0
        n      = len(pnls)
        mu     = sum(pnls) / n - rf
        losses = [p for p in pnls if p < rf]
        if not losses: return 10.0
        down_var = sum(p ** 2 for p in losses) / n
        down_std = math.sqrt(down_var)
        return mu / down_std * math.sqrt(252) if down_std > 0 else 0.0

    @staticmethod
    def _streaks(pnls: list[float]) -> tuple[int, int]:
        mc_w = mc_l = cur_w = cur_l = 0
        for p in pnls:
            if p > 0:
                cur_w += 1; cur_l = 0
            else:
                cur_l += 1; cur_w = 0
            mc_w = max(mc_w, cur_w)
            mc_l = max(mc_l, cur_l)
        return mc_w, mc_l

    @staticmethod
    def _grade(wr: float, pf: float, sharpe: float, max_dd: float) -> tuple[str, str]:
        pts = 0
        if wr >= 55:  pts += 2
        elif wr >= 45: pts += 1
        if pf >= 2.0: pts += 2
        elif pf >= 1.5: pts += 1
        if sharpe >= 1.5: pts += 2
        elif sharpe >= 0.8: pts += 1
        if max_dd <= 5:  pts += 2
        elif max_dd <= 10: pts += 1

        if pts >= 8:  return "A+", "Exceptional — deploy with confidence"
        if pts >= 6:  return "A",  "Strong edge — monitor and scale"
        if pts >= 4:  return "B",  "Positive edge — continue developing"
        if pts >= 2:  return "C",  "Marginal — review signal quality"
        return "F",  "No edge detected — do NOT trade live"
