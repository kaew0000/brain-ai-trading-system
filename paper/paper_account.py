"""
Paper Trading: Account

Tracks virtual balance, equity, margin, and daily PnL.
Thread-safe; all state lives in memory — no DB dependency.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

STARTING_BALANCE: float = 1_000.0   # USDT — override via PaperAccount(balance=X)


@dataclass
class AccountSnapshot:
    timestamp:       str
    balance:         float   # realised equity (closed PnL absorbed)
    equity:          float   # balance + open unrealised PnL
    used_margin:     float
    free_margin:     float
    unrealised_pnl:  float
    total_trades:    int
    open_trades:     int


class PaperAccount:
    """
    Virtual futures account with leverage.

    All monetary values in USDT.
    """

    def __init__(
        self,
        balance:  float = STARTING_BALANCE,
        leverage: int   = None,
    ) -> None:
        self._lock         = threading.Lock()
        self._balance      = float(balance)          # realised
        self._unrealised   = 0.0
        self._used_margin  = 0.0
        self._leverage     = leverage or settings.LEVERAGE
        self._total_trades = 0
        self._open_trades  = 0

        # Daily tracking (reset at midnight)
        self._day_start_balance = self._balance
        self._day_pnl           = 0.0
        self._day_date          = datetime.now(timezone.utc).date()

        # Equity curve (one point per closed trade)
        self._equity_curve: List[dict] = []

        logger.info(
            f"PaperAccount ready | balance={self._balance:.2f} U "
            f"leverage={self._leverage}x"
        )

    # ── Read-only properties ──────────────────────────────────────────────────

    @property
    def balance(self) -> float:
        with self._lock:
            return self._balance

    @property
    def equity(self) -> float:
        with self._lock:
            return self._balance + self._unrealised

    @property
    def free_margin(self) -> float:
        with self._lock:
            return self._balance - self._used_margin

    @property
    def used_margin(self) -> float:
        with self._lock:
            return self._used_margin

    @property
    def unrealised_pnl(self) -> float:
        with self._lock:
            return self._unrealised

    @property
    def leverage(self) -> int:
        return self._leverage

    @property
    def day_pnl(self) -> float:
        with self._lock:
            self._maybe_reset_day()
            return self._day_pnl

    @property
    def day_pnl_pct(self) -> float:
        with self._lock:
            self._maybe_reset_day()
            if self._day_start_balance == 0:
                return 0.0
            return round(self._day_pnl / self._day_start_balance, 6)

    # ── Margin management ─────────────────────────────────────────────────────

    def reserve_margin(self, notional: float) -> bool:
        """
        Reserve margin for a new position.

        Parameters
        ----------
        notional : position size in USDT (qty × entry_price)

        Returns True if margin was reserved, False if insufficient.
        """
        required = notional / self._leverage
        with self._lock:
            if required > self._balance - self._used_margin:
                logger.warning(
                    f"Insufficient margin: required={required:.2f} "
                    f"free={self._balance - self._used_margin:.2f}"
                )
                return False
            self._used_margin  += required
            self._open_trades  += 1
            self._total_trades += 1
            return True

    def release_margin(self, notional: float) -> None:
        """Release margin when a position closes."""
        released = notional / self._leverage
        with self._lock:
            self._used_margin = max(0.0, self._used_margin - released)
            self._open_trades = max(0, self._open_trades - 1)

    def update_unrealised(self, total_unrealised: float) -> None:
        """Called every mark-price tick by PaperPosition."""
        with self._lock:
            self._unrealised = total_unrealised

    def realise_pnl(self, pnl: float) -> None:
        """
        Absorb closed-trade PnL into balance.
        Appends an equity curve point.
        """
        with self._lock:
            self._maybe_reset_day()
            self._balance   += pnl
            self._day_pnl   += pnl
            # Do NOT reduce _unrealised here: tick() calls update_unrealised()
            # after each closed position, which sets the correct running total.
            # Subtracting abs(pnl) can go negative for large losses and corrupts equity.
            self._equity_curve.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "equity":    round(self._balance, 4),
                "pnl":       round(pnl, 4),
            })
            logger.info(
                f"PnL realised: {pnl:+.2f} U → balance={self._balance:.2f} U"
            )

    # ── Snapshot / Metrics ────────────────────────────────────────────────────

    def snapshot(self) -> AccountSnapshot:
        with self._lock:
            equity = self._balance + self._unrealised
            return AccountSnapshot(
                timestamp      = datetime.now(timezone.utc).isoformat(),
                balance        = round(self._balance,     4),
                equity         = round(equity,            4),
                used_margin    = round(self._used_margin, 4),
                free_margin    = round(self._balance - self._used_margin, 4),
                unrealised_pnl = round(self._unrealised,  4),
                total_trades   = self._total_trades,
                open_trades    = self._open_trades,
            )

    def to_dict(self) -> dict:
        snap = self.snapshot()
        return {
            "timestamp":      snap.timestamp,
            "balance":        snap.balance,
            "equity":         snap.equity,
            "used_margin":    snap.used_margin,
            "free_margin":    snap.free_margin,
            "unrealised_pnl": snap.unrealised_pnl,
            "total_trades":   snap.total_trades,
            "open_trades":    snap.open_trades,
            "leverage":       self._leverage,
            "day_pnl":        round(self._day_pnl, 4),
            "day_pnl_pct":    round(self.day_pnl_pct * 100, 4),
        }

    @property
    def equity_curve(self) -> List[dict]:
        with self._lock:
            return list(self._equity_curve)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _maybe_reset_day(self) -> None:
        """Reset daily PnL counter at UTC midnight (call inside lock)."""
        today = datetime.now(timezone.utc).date()
        if today != self._day_date:
            self._day_start_balance = self._balance
            self._day_pnl   = 0.0
            self._day_date  = today
