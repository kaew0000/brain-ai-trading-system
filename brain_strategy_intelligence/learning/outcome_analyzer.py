"""Outcome analysis and periodic reporting. Read-only: never edits strategies or trading logic.

Failure classification is a documented HEURISTIC, applied in this priority order to LOSING trades:
  1 data_quality                  - the record carries data_quality_flags
  2 poor_execution                - realized slippage > ratio x expected slippage
  3 incorrect_market_assumption   - regime at decision was outside the strategy's declared market_conditions
  4 possible_strategy_degradation - recent win rate is significantly below the strategy's earlier baseline
                                    (one-sided two-proportion z-test; needs min_samples on BOTH sides)
  5 normal_variance               - none of the above
Anything else (WIN / BREAKEVEN) carries failure_class=None.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from ..config import LearningCfg
from ..schemas import OutcomeAnalysis, TradeRecord
from .trade_recorder import mfe_mae, net_pnl


def _degraded(history: Sequence[TradeRecord], n: int, z_crit: float) -> bool:
    if len(history) < 2 * n:
        return False
    recent, base = history[-n:], history[:-n]
    if len(base) < n:
        return False
    p1 = sum(1 for t in recent if net_pnl(t) > 0) / len(recent)
    p0 = sum(1 for t in base if net_pnl(t) > 0) / len(base)
    pooled = (p1 * len(recent) + p0 * len(base)) / (len(recent) + len(base))
    se = math.sqrt(pooled * (1 - pooled) * (1 / len(recent) + 1 / len(base)))
    return se > 0 and (p0 - p1) / se > z_crit


class OutcomeAnalyzer:
    def __init__(self, cfg: LearningCfg) -> None:
        self.cfg = cfg

    def classify(
        self, t: TradeRecord, *, declared_regimes: Sequence[str] | None = None, prior_trades: Sequence[TradeRecord] = ()
    ) -> OutcomeAnalysis:
        net = net_pnl(t)
        mfe, mae = mfe_mae(t)
        outcome = "WIN" if net > 0 else "LOSS" if net < 0 else "BREAKEVEN"
        if outcome != "LOSS":
            return OutcomeAnalysis(trade_id=t.trade_id, outcome=outcome, net_pnl=net, mfe=mfe, mae=mae)
        reasons: list[str] = []
        fc = "normal_variance"
        if t.data_quality_flags:
            fc, reasons = "data_quality", [f"data quality flags: {', '.join(t.data_quality_flags)}"]
        elif (
            t.expected_slippage_bps is not None
            and t.realized_slippage_bps is not None
            and t.realized_slippage_bps > self.cfg.poor_execution_slippage_ratio * max(t.expected_slippage_bps, 0.01)
        ):
            fc = "poor_execution"
            reasons = [
                f"realized slippage {t.realized_slippage_bps:.1f} bps vs expected {t.expected_slippage_bps:.1f} bps"
            ]
        elif declared_regimes and t.regime and t.regime not in {r.upper() for r in declared_regimes}:
            fc = "incorrect_market_assumption"
            reasons = [
                f"regime {t.regime} not in strategy's declared conditions {sorted(r.upper() for r in declared_regimes)}"
            ]
        elif _degraded(prior_trades, self.cfg.min_samples_degradation, self.cfg.degradation_z):
            fc = "possible_strategy_degradation"
            reasons = ["recent win rate significantly below the earlier baseline (statistical heuristic, not proof)"]
        else:
            reasons = ["no execution, data or regime problem detected; consistent with normal variance"]
        return OutcomeAnalysis(
            trade_id=t.trade_id, outcome="LOSS", net_pnl=net, mfe=mfe, mae=mae, failure_class=fc, reasons=reasons
        )  # type: ignore[arg-type]

    def analyze_all(
        self, trades: Sequence[TradeRecord], declared: Mapping[str, Sequence[str]] | None = None
    ) -> list[OutcomeAnalysis]:
        """Classify verified trades chronologically; each loss only sees the trades BEFORE it (no look-ahead)."""
        by_key: dict[tuple[str, int], list[TradeRecord]] = defaultdict(list)
        out: list[OutcomeAnalysis] = []
        for t in sorted(trades, key=lambda x: (x.exit_time, x.trade_id)):
            if not t.verified or t.status != "CLOSED":
                continue
            key = (t.strategy_id, t.strategy_version)
            out.append(self.classify(t, declared_regimes=(declared or {}).get(t.strategy_id), prior_trades=by_key[key]))
            by_key[key].append(t)
        return out

    def performance_report(
        self, trades: Sequence[TradeRecord], declared: Mapping[str, Sequence[str]] | None = None
    ) -> dict[str, Any]:
        verified = [t for t in trades if t.verified and t.status == "CLOSED"]
        analyses = {a.trade_id: a for a in self.analyze_all(verified, declared)}
        groups: dict[tuple[str, int], list[TradeRecord]] = defaultdict(list)
        for t in verified:
            groups[(t.strategy_id, t.strategy_version)].append(t)
        rows = []
        for (sid, ver), ts in sorted(groups.items()):
            nets = [net_pnl(t) for t in ts]
            fails: dict[str, int] = defaultdict(int)
            for t in ts:
                if fc := analyses[t.trade_id].failure_class:
                    fails[fc] += 1
            rows.append(
                {
                    "strategy_id": sid,
                    "version": ver,
                    "trades": len(ts),
                    "win_rate": sum(1 for x in nets if x > 0) / len(nets),
                    "net_pnl": sum(nets),
                    "expectancy": sum(nets) / len(nets),
                    "failure_classes": dict(fails),
                    "low_sample": len(ts) < self.cfg.min_samples_degradation,
                }
            )
        return {
            "verified_trades": len(verified),
            "excluded_unverified_or_open": len(trades) - len(verified),
            "strategies": rows,
            "note": "net_pnl = realized_pnl - fees - funding; only verified CLOSED trades are included",
        }
