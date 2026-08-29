"""
PortfolioStateAdapter — best-effort, real portfolio snapshot for
ml.extensions.rl.adapter.TradingPolicy.get_action(), which reads
portfolio_state["equity"] and portfolio_state["position"] (see
ml/extensions/rl/adapter.py's TradingPolicy.get_action).

Scope note: portfolio/portfolio_manager.py's PortfolioManager.status()
returns *configured limits* (max_positions, cooldowns, ...), not live
balance/position numbers — that data instead lives on
portfolio/portfolio_state.py's PortfolioState (position/PnL/risk
tracking) and data/binance_provider.py's BinanceDataProvider (account
balance). This adapter combines those two real sources rather than
inventing a single "portfolio_intelligence.get_summary()" method, which
does not exist anywhere in this codebase.

Known, documented limitation: PortfolioState has no single "net
position ratio" field the way BrainTradingEnv's own internal simulated
portfolio does. `position` below is PortfolioState.risk_used (the
existing capital-at-risk fraction it already computes) used as the
closest real proxy — not a literal position/equity ratio. This is
acceptable for this phase because MLExtensionsAgent (this integration
layer) is observe-only: nothing here executes real orders, so precision
here affects a dashboard number, not capital.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)


class PortfolioStateAdapter:
    """Wraps optional real portfolio_state / data_provider references.
    Every method degrades to safe zeroed defaults if a source is
    missing or a read fails — never raises."""

    def __init__(self, portfolio_state: Optional[Any] = None, data_provider: Optional[Any] = None) -> None:
        self.portfolio_state = portfolio_state
        self.data_provider = data_provider

    def get_state_for_rl(self) -> dict:
        balance = 0.0
        if self.data_provider is not None:
            try:
                balance = float(self.data_provider.get_account_balance())
            except Exception as exc:
                logger.debug(f"PortfolioStateAdapter: get_account_balance unavailable: {exc}")

        floating_pnl = 0.0
        risk_used = 0.0
        position_count = 0
        drawdown = 0.0
        if self.portfolio_state is not None:
            try:
                floating_pnl = float(self.portfolio_state.floating_pnl)
                risk_used = float(self.portfolio_state.risk_used)
                position_count = int(self.portfolio_state.position_count)
                if balance:
                    drawdown = float(self.portfolio_state.portfolio_drawdown(balance))
            except Exception as exc:
                logger.debug(f"PortfolioStateAdapter: PortfolioState read failed: {exc}")

        equity = balance + floating_pnl
        return {
            "equity": equity,
            "balance": balance,
            "position": risk_used,  # proxy — see module docstring
            "unrealized_pnl": floating_pnl,
            "position_count": float(position_count),
            "current_drawdown": drawdown,
        }
