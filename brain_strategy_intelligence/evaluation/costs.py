"""Trading cost model: fees, slippage, funding. All rates come from configuration (never hardcoded)."""

from __future__ import annotations

from dataclasses import dataclass

from ..config import EvaluationCfg

SECONDS_PER_FUNDING_INTERVAL = 8 * 3600


@dataclass(frozen=True)
class CostModel:
    fee_bps: float
    slippage_bps: float
    funding_rate_per_8h: float
    include_funding: bool
    funding_conservative: bool

    @classmethod
    def from_config(cls, cfg: EvaluationCfg) -> CostModel:
        return cls(
            cfg.fee_bps, cfg.slippage_bps, cfg.funding_rate_per_8h, cfg.include_funding, cfg.funding_conservative
        )

    def fill_price(self, price: float, side: int) -> float:
        """side=+1 buying (pay up), -1 selling (receive less). Slippage is always adverse."""
        return price * (1.0 + side * self.slippage_bps / 1e4)

    def fee(self, notional: float) -> float:
        return abs(notional) * self.fee_bps / 1e4

    def funding_cost(self, notional: float, direction: int, bar_seconds: int) -> float:
        """Cost (positive = paid) for holding `notional` for one bar. Conservative mode never credits shorts."""
        if not self.include_funding:
            return 0.0
        rate = self.funding_rate_per_8h * bar_seconds / SECONDS_PER_FUNDING_INTERVAL
        return abs(rate) * notional if self.funding_conservative else rate * direction * notional
