"""Transparent, configurable strategy ranking.

Score = weighted sum of eight 0..1 components (weights in config, summing to 1). Profit alone cannot win:
return only enters via return-over-drawdown, and drawdown, stability, reliability, degradation, sensitivity
and cost drag all carry weight. INCOMPLETE evaluations are never ranked. Ranking never changes a strategy's
validation status.
"""

from __future__ import annotations

from ..config import RankingCfg
from ..schemas import EvaluationResult, RankedStrategy, RankingReport, StrategyDefinition


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


class StrategyRanker:
    def __init__(self, cfg: RankingCfg) -> None:
        self.cfg = cfg

    def _score_one(self, s: StrategyDefinition, ev: EvaluationResult) -> RankedStrategy:
        c = self.cfg
        base = dict(
            strategy_id=s.id,
            strategy_version=s.version,
            validation_status=s.validation_status,
            data_label=ev.data_label,
        )
        if ev.status != "COMPLETE" or ev.out_of_sample is None or ev.in_sample is None:
            return RankedStrategy(
                **base,
                rank=None,
                score=None,
                status="UNRANKED",
                reasons=["evaluation incomplete: " + "; ".join(ev.incomplete_reasons or ["no metrics"])],
                limitations=["no performance claims can be made"],
            )
        oos, ins = ev.out_of_sample, ev.in_sample
        reasons: list[str] = []
        lim: list[str] = []
        comp: dict[str, float | None] = {}

        # 1 profit factor (OOS). Undefined PF (no losing trades) is treated neutrally, not as perfect.
        if oos.profit_factor is None:
            comp["oos_profit_factor"] = 0.5
            lim.append("OOS profit factor undefined (no losing trades or no winners) - scored neutral 0.5")
        else:
            comp["oos_profit_factor"] = _clip(oos.profit_factor - 1.0)
        # 2 return over drawdown
        rod = oos.return_over_drawdown
        if rod is None:
            comp["return_over_drawdown"] = 0.0 if oos.return_pct <= 0 else 0.5
            lim.append("return/drawdown undefined (zero drawdown) - treated conservatively")
        else:
            comp["return_over_drawdown"] = _clip(rod / 2.0)
        # 3 drawdown
        comp["drawdown"] = _clip(1.0 - oos.max_drawdown_pct / c.max_acceptable_drawdown_pct)
        # 4 stability across walk-forward windows (proxy for regime stability)
        wf = ev.walk_forward
        if wf is None or wf.profitable_fraction is None:
            comp["regime_stability"] = 0.0
            lim.append("no walk-forward result: stability scored 0")
        else:
            comp["regime_stability"] = wf.profitable_fraction
            if len(wf.windows) < 4:
                lim.append(f"only {len(wf.windows)} walk-forward windows - stability estimate is coarse")
        # 5 statistical reliability
        comp["reliability"] = _clip(oos.trade_count / c.min_reliable_trades)
        if oos.trade_count < c.min_reliable_trades:
            lim.append(f"only {oos.trade_count} OOS trades (< {c.min_reliable_trades}) - low statistical reliability")
        # 6 degradation between in-sample and out-of-sample (per-bar return)
        is_rate, oos_rate = ins.return_pct / max(ins.bars, 1), oos.return_pct / max(oos.bars, 1)
        if is_rate <= 0:
            comp["degradation"] = 1.0 if oos_rate > 0 else 0.0
            lim.append("no positive in-sample edge to degrade from")
        else:
            deg = _clip((is_rate - oos_rate) / is_rate)
            comp["degradation"] = 1.0 - deg
            if deg > 0.5:
                reasons.append(f"OOS per-bar return is {deg:.0%} below in-sample (possible overfitting)")
        # 7 parameter sensitivity
        sens = ev.sensitivity
        if sens is None or sens.positive_neighbour_fraction is None:
            comp["sensitivity"] = 0.0
            lim.append("no sensitivity analysis: scored 0")
        else:
            comp["sensitivity"] = sens.positive_neighbour_fraction
            if sens.positive_neighbour_fraction < 0.5:
                reasons.append("fewer than half of perturbed parameter sets were profitable (fragile)")
        # 8 transaction-cost drag (costs already deducted from net figures; this rewards cost-light edges)
        costs = oos.fees_paid + oos.slippage_cost + oos.funding_paid
        gross = oos.net_pnl + costs  # PnL before ALL costs (slippage is embedded in fills, so add it back)
        comp["cost_drag"] = _clip(1.0 - costs / gross) if gross > 0 else 0.0
        if gross <= 0:
            lim.append("no gross OOS profit: cost drag scored 0")

        score = sum(c.weights[k] * (v or 0.0) for k, v in comp.items())
        if oos.net_pnl <= 0:
            score *= c.negative_oos_penalty
            reasons.append(f"negative OOS net PnL ({oos.net_pnl:.2f}): score multiplied by {c.negative_oos_penalty}")
        else:
            reasons.append(f"positive OOS net PnL ({oos.net_pnl:.2f}) after fees, slippage and funding")
        if "SYNTHETIC" in ev.data_label.upper():
            lim.append("evaluated on SYNTHETIC data - ranking demonstrates the machinery only")
        if s.validation_status.value != "validated":
            lim.append(f"strategy status is '{s.validation_status.value}', not validated")
        return RankedStrategy(
            **base, rank=None, score=round(score, 6), status="RANKED", breakdown=comp, reasons=reasons, limitations=lim
        )

    def rank(self, items: list[tuple[StrategyDefinition, EvaluationResult]]) -> RankingReport:
        scored = [self._score_one(s, ev) for s, ev in items]
        ranked = sorted((r for r in scored if r.status == "RANKED"), key=lambda r: (-(r.score or 0.0), r.strategy_id))
        unranked = sorted((r for r in scored if r.status == "UNRANKED"), key=lambda r: r.strategy_id)
        for i, r in enumerate(ranked, start=1):
            r.rank = i
        return RankingReport(weights=dict(self.cfg.weights), entries=[*ranked, *unranked])
