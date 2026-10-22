"""StrategyEvaluator: orchestrates validation -> split -> backtests -> walk-forward -> sensitivity.

Never fabricates: if data or trades are insufficient the result is INCOMPLETE with explicit reasons.
"""

from __future__ import annotations

import hashlib
import json
import logging
from statistics import median

from ..config import Config
from ..schemas import Candle, EvaluationResult, StrategyDefinition
from .backtester import compute_metrics, run_backtest
from .data import TIMEFRAME_SECONDS
from .engines import get_engine
from .walk_forward import parameter_sensitivity, run_walk_forward, split_indices

log = logging.getLogger(__name__)


def data_fingerprint(candles: list[Candle]) -> str:
    h = hashlib.sha256()
    for c in candles:
        h.update(f"{c.ts}:{c.close:.10g};".encode())
    return h.hexdigest()[:16]


class StrategyEvaluator:
    def __init__(self, config: Config) -> None:
        self.cfg = config
        self.ev = config.evaluation

    def _assumptions(self) -> list[str]:
        e = self.ev
        return [
            "signals computed at bar close; fills at NEXT bar open with adverse slippage (no look-ahead)",
            f"fees {e.fee_bps} bps/side and slippage {e.slippage_bps} bps/side are configured ASSUMPTIONS",
            (
                f"funding: constant {e.funding_rate_per_8h}/8h ASSUMPTION ({'both sides charged' if e.funding_conservative else 'signed'})"
                if e.include_funding
                else "funding excluded by configuration"
            ),
            f"sizing: notional = {e.position_pct:.0%} of equity, gross leverage cap {e.max_leverage}x; liquidation not modelled",
            f"stop-loss: {e.stop_loss_pct if e.stop_loss_pct else 'none'}; gaps through a stop fill at the worse open",
            "single asset, one position at a time, no partial fills or order-book depth model",
        ]

    def evaluate(
        self, strategy: StrategyDefinition, candles: list[Candle], *, symbol: str, timeframe: str, data_label: str
    ) -> EvaluationResult:
        e = self.ev
        reasons: list[str] = []
        warnings: list[str] = []
        fp = data_fingerprint(candles)
        eid = hashlib.sha256(
            "|".join(
                [
                    strategy.id,
                    str(strategy.version),
                    json.dumps(strategy.parameters, sort_keys=True),
                    json.dumps(strategy.param_grid, sort_keys=True),
                    fp,
                    self.cfg.fingerprint(),
                    symbol,
                    timeframe,
                ]
            ).encode()
        ).hexdigest()[:16]

        def result(status: str = "INCOMPLETE", **kw) -> EvaluationResult:
            return EvaluationResult(
                evaluation_id=eid,
                strategy_id=strategy.id,
                strategy_version=strategy.version,
                symbol=symbol,
                timeframe=timeframe,
                data_label=data_label,
                status=status,
                incomplete_reasons=reasons,
                warnings=warnings,
                assumptions=self._assumptions(),
                config_fingerprint=self.cfg.fingerprint(),
                **kw,
            )

        engine = get_engine(strategy.engine)
        if engine is None:
            reasons.append(
                f"no executable engine for strategy (engine={strategy.engine!r}, category={strategy.category.value}); "
                "knowledge-only strategies cannot be backtested here"
            )
            return result()
        try:
            engine.validate(strategy.parameters)
        except (ValueError, TypeError) as exc:
            reasons.append(f"invalid parameters: {exc}")
            return result()
        n = len(candles)
        if n < e.min_bars:
            reasons.append(f"insufficient history: {n} bars < min_bars {e.min_bars}")
            return result()
        ts = [c.ts for c in candles]
        if any(b <= a for a, b in zip(ts, ts[1:], strict=False)):
            reasons.append("candles are not strictly increasing in time (duplicates or disorder)")
            return result()
        diffs = [b - a for a, b in zip(ts, ts[1:], strict=False)]
        bar_seconds = int(median(diffs))
        gaps = sum(1 for d in diffs if d > 1.5 * bar_seconds)
        if gaps / len(diffs) > e.max_gap_fraction:
            reasons.append(f"too many gaps in data: {gaps}/{len(diffs)} intervals exceed 1.5x the bar size")
            return result()
        if gaps:
            warnings.append(f"{gaps} gap(s) in data (within tolerance)")
        expected = TIMEFRAME_SECONDS.get(timeframe)
        if expected and expected != bar_seconds:
            warnings.append(
                f"timeframe label {timeframe} ({expected}s) disagrees with inferred bar size {bar_seconds}s"
            )
        if data_label.upper().startswith("SYNTHETIC"):
            warnings.append("SYNTHETIC data: results demonstrate the machinery only and say nothing about real markets")

        a, b = split_indices(n, e.split)
        try:

            def seg(lo: int, hi: int):
                r = run_backtest(
                    candles, engine, strategy.parameters, e, bar_seconds=bar_seconds, trade_start=lo, trade_end=hi
                )
                if r.bankrupt:
                    warnings.append(f"equity exhausted in segment [{lo},{hi})")
                return compute_metrics(r, bar_seconds)

            m_is, m_val, m_oos = seg(0, a), seg(a, b), seg(b, n)
            wf, wf_notes = run_walk_forward(candles, strategy, engine, e, bar_seconds)
            sens = parameter_sensitivity(candles, strategy, engine, e, bar_seconds, a, b)
        except (ValueError, TypeError, KeyError) as exc:
            reasons.append(f"evaluation error: {exc}")
            return result()

        if m_oos.trade_count < e.min_oos_trades:
            reasons.append(f"out-of-sample trades {m_oos.trade_count} < min_oos_trades {e.min_oos_trades}")
        if wf is None:
            reasons.append("walk-forward unavailable: " + "; ".join(wf_notes))
        elif len(wf.windows) < e.min_wf_windows:
            reasons.append(f"only {len(wf.windows)} walk-forward window(s) < min_wf_windows {e.min_wf_windows}")
        if sens is None:
            warnings.append("parameter sensitivity unavailable (no perturbable numeric parameters)")
        status = "INCOMPLETE" if reasons else "COMPLETE"
        return result(status, in_sample=m_is, validation=m_val, out_of_sample=m_oos, walk_forward=wf, sensitivity=sens)
