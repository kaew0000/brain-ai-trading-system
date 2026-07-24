"""
portfolio/portfolio_state.py — V16 Phase 2A: Portfolio Intelligence Core

Pure in-memory state container. No exchange calls, no database, no
network — mirrors PaperAccount's philosophy (paper/paper_account.py) of
"this class just tracks numbers", except here nothing even simulates
fills; it only holds whatever PortfolioPosition objects it's given.

Who constructs and keeps this in sync with reality is explicitly out of
scope for 2A. 2B's orchestrator will own reading real exchange/journal
state into a PortfolioState each cycle; today this class is exercised by
tests constructing it directly, and by CapitalManager reading from it.
"""
from __future__ import annotations


from portfolio.portfolio_models import PortfolioPosition


class PortfolioState:

    def __init__(
        self,
        daily_pnl: float = 0.0,
        floating_pnl: float = 0.0,
        peak_balance: float | None = None,
    ) -> None:
        self._positions: dict[str, PortfolioPosition] = {}
        self.daily_pnl     = daily_pnl
        self.floating_pnl  = floating_pnl
        self._peak_balance = peak_balance

    # ── Position tracking ───────────────────────────────────────────────

    def add_position(self, position: PortfolioPosition) -> None:
        """Adds or replaces the position for its symbol. One position per
        symbol — a second add_position() for the same symbol overwrites
        (e.g. a PARTIAL → OPEN state transition), it does not stack."""
        self._positions[position.symbol] = position

    def remove_position(self, symbol: str) -> PortfolioPosition | None:
        return self._positions.pop(symbol, None)

    def get_position(self, symbol: str) -> PortfolioPosition | None:
        return self._positions.get(symbol)

    def has_position(self, symbol: str) -> bool:
        return symbol in self._positions

    @property
    def active_positions(self) -> list[PortfolioPosition]:
        """Positions in any non-terminal state. CLOSED/ARCHIVED positions
        should be removed via remove_position() rather than left in here —
        this property doesn't filter them out, by design, so a caller that
        forgets to clean up notices (stale notional inflates exposure)
        rather than silently getting a "correct-looking" filtered view."""
        return list(self._positions.values())

    @property
    def position_count(self) -> int:
        return len(self._positions)

    @property
    def held_symbols(self) -> list[str]:
        return list(self._positions.keys())

    # ── Capital / exposure ──────────────────────────────────────────────

    @property
    def reserved_capital(self) -> float:
        return sum(p.margin_used for p in self._positions.values())

    def free_capital(self, balance: float) -> float:
        return max(0.0, balance - self.reserved_capital)

    @property
    def risk_used(self) -> float:
        """Sum of margin_used across open positions — a proxy for
        capital-at-risk. This is NOT the same thing as RiskBudget's
        risk_used_open_usdt (which CapitalManager computes with its own,
        stop-loss-distance-aware definition of risk) — this property
        answers "how much margin is tied up", not "how much could be
        lost"; kept separate and named distinctly so the two aren't
        accidentally used interchangeably."""
        return self.reserved_capital

    def symbol_exposure(self, symbol: str) -> float:
        """Notional exposure (USDT) for one symbol, 0.0 if not held."""
        p = self._positions.get(symbol)
        return p.notional if p else 0.0

    def sector_exposure(self, sector: str) -> float:
        """Notional exposure (USDT) summed across all held positions
        tagged with this sector. Returns 0.0 for every sector today since
        PortfolioPosition.sector is always None until 2B's Sector Engine
        assigns real values — present now so callers don't need to change
        once it's populated."""
        return sum(
            p.notional for p in self._positions.values() if p.sector == sector
        )

    # ── PnL / drawdown ───────────────────────────────────────────────────

    def portfolio_drawdown(self, current_balance: float) -> float:
        """
        Fraction below peak_balance (0.0 = at/above peak). peak_balance
        must be supplied at construction or via record_balance() — this
        class does not fetch balance from anywhere, so if no peak has
        ever been recorded, current_balance itself becomes the peak
        (drawdown 0.0) rather than raising.
        """
        if self._peak_balance is None or current_balance > self._peak_balance:
            self._peak_balance = current_balance
            return 0.0
        if self._peak_balance <= 0:
            return 0.0
        return max(0.0, (self._peak_balance - current_balance) / self._peak_balance)

    def record_balance(self, balance: float) -> None:
        """Explicit peak-tracking hook, for callers (2B) that poll balance
        on a schedule rather than only at decision time."""
        if self._peak_balance is None or balance > self._peak_balance:
            self._peak_balance = balance

    @property
    def peak_balance(self) -> float | None:
        return self._peak_balance

    def to_dict(self, balance: float | None = None) -> dict:
        return {
            "positions":        {s: p.to_dict() for s, p in self._positions.items()},
            "position_count":   self.position_count,
            "reserved_capital": self.reserved_capital,
            "free_capital":     self.free_capital(balance) if balance is not None else None,
            "risk_used":        self.risk_used,
            "daily_pnl":        self.daily_pnl,
            "floating_pnl":     self.floating_pnl,
            "peak_balance":     self._peak_balance,
            "drawdown":         self.portfolio_drawdown(balance) if balance is not None else None,
        }
