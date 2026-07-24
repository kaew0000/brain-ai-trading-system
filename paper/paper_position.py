"""
Paper Trading: Position

Tracks a single open paper position.
Calculates unrealised PnL, R:R, and closing metrics.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ClosedTrade:
    """Immutable result of a closed paper position."""
    position_id: str
    symbol:      str
    direction:   str        # LONG | SHORT
    entry_price: float
    exit_price:  float
    quantity:    float
    stop_loss:   float
    take_profit: float
    pnl:         float      # USDT (net of fees)
    pnl_pct:     float      # % of notional
    rr:          float      # realised R:R
    result:      str        # WIN | LOSS | BREAKEVEN
    opened_at:   str        # ISO-8601
    closed_at:   str        # ISO-8601
    duration_s:  int        # seconds open
    close_reason: str       # SL | TP | MANUAL | TIMEOUT
    confidence:  int        # ConfidenceResult.confidence at entry
    regime:      str
    oi_delta:    float
    funding_rate: float

    def to_dict(self) -> dict:
        return {
            "position_id":  self.position_id,
            "symbol":       self.symbol,
            "direction":    self.direction,
            "entry_price":  self.entry_price,
            "exit_price":   self.exit_price,
            "quantity":     self.quantity,
            "stop_loss":    self.stop_loss,
            "take_profit":  self.take_profit,
            "pnl":          round(self.pnl,     4),
            "pnl_pct":      round(self.pnl_pct, 6),
            "rr":           round(self.rr,      3),
            "result":       self.result,
            "opened_at":    self.opened_at,
            "closed_at":    self.closed_at,
            "duration_s":   self.duration_s,
            "close_reason": self.close_reason,
            "confidence":   self.confidence,
            "regime":       self.regime,
            "oi_delta":     self.oi_delta,
            "funding_rate": self.funding_rate,
        }


class PaperPosition:
    """
    A single open paper-trading position.

    Thread-safe via immutable fields post-construction;
    only `update_mark()` mutates state, protected by caller.
    """

    FEE_RATE = 0.0004      # 0.04% taker per side (Binance Futures default)
    TIMEOUT_BARS = 96      # ~24 h at M15 — auto-close if no SL/TP hit

    def __init__(
        self,
        symbol:       str,
        direction:    str,
        entry_price:  float,
        stop_loss:    float,
        take_profit:  float,
        quantity:     float,
        leverage:     int,
        confidence:   int   = 0,
        regime:       str   = "",
        oi_delta:     float = 0.0,
        funding_rate: float = 0.0,
    ) -> None:
        if direction not in ("LONG", "SHORT"):
            raise ValueError(f"direction must be LONG|SHORT, got {direction!r}")
        if quantity <= 0:
            raise ValueError(f"quantity must be > 0, got {quantity}")

        self.position_id  = str(uuid.uuid4())[:8]
        self.symbol       = symbol
        self.direction    = direction
        self.entry_price  = float(entry_price)
        self.stop_loss    = float(stop_loss)
        self.take_profit  = float(take_profit)
        self.quantity     = float(quantity)
        self.leverage     = int(leverage)
        self.confidence   = int(confidence)
        self.regime       = regime
        self.oi_delta     = float(oi_delta)
        self.funding_rate = float(funding_rate)

        self.opened_at   = datetime.now(timezone.utc)
        self.mark_price  = self.entry_price
        self._bars_open  = 0
        self.is_open     = True

        # Precompute risk (entry → SL distance in USDT per contract)
        if direction == "LONG":
            self._risk_per_unit = self.entry_price - self.stop_loss
        else:
            self._risk_per_unit = self.stop_loss - self.entry_price

        notional = self.entry_price * self.quantity
        self._entry_fee = notional * self.FEE_RATE

        logger.info(
            f"PaperPosition opened | id={self.position_id} "
            f"{direction} {quantity:.6f} @ {entry_price:.2f} "
            f"SL={stop_loss:.2f} TP={take_profit:.2f}"
        )

    # ── Mark price ────────────────────────────────────────────────────────────

    def update_mark(self, mark_price: float) -> ClosedTrade | None:
        """
        Update mark price. Checks SL/TP hit.
        Returns ClosedTrade if position was closed, else None.
        """
        if not self.is_open:
            return None
        self.mark_price = float(mark_price)
        self._bars_open += 1

        if self._sl_hit():
            return self._close(self.stop_loss,   "SL")
        if self._tp_hit():
            return self._close(self.take_profit, "TP")
        if self._bars_open >= self.TIMEOUT_BARS:
            return self._close(self.mark_price,  "TIMEOUT")
        return None

    def close_manual(self, exit_price: float) -> ClosedTrade:
        """Force-close at given price."""
        return self._close(float(exit_price), "MANUAL")

    # ── Unrealised PnL ────────────────────────────────────────────────────────

    @property
    def unrealised_pnl(self) -> float:
        if self.direction == "LONG":
            return (self.mark_price - self.entry_price) * self.quantity
        return (self.entry_price - self.mark_price) * self.quantity

    @property
    def unrealised_pnl_pct(self) -> float:
        notional = self.entry_price * self.quantity
        return self.unrealised_pnl / notional if notional else 0.0

    @property
    def notional(self) -> float:
        return self.entry_price * self.quantity

    def to_dict(self) -> dict:
        return {
            "position_id":     self.position_id,
            "symbol":          self.symbol,
            "direction":       self.direction,
            "entry_price":     self.entry_price,
            "mark_price":      round(self.mark_price, 2),
            "stop_loss":       self.stop_loss,
            "take_profit":     self.take_profit,
            "quantity":        self.quantity,
            "leverage":        self.leverage,
            "unrealised_pnl":  round(self.unrealised_pnl,     4),
            "unrealised_pct":  round(self.unrealised_pnl_pct, 6),
            "notional":        round(self.notional,            2),
            "opened_at":       self.opened_at.isoformat(),
            "bars_open":       self._bars_open,
            "confidence":      self.confidence,
            "regime":          self.regime,
            "oi_delta":        self.oi_delta,
            "funding_rate":    self.funding_rate,
            "is_open":         self.is_open,
        }

    # ── Internal ──────────────────────────────────────────────────────────────

    def _sl_hit(self) -> bool:
        if self.direction == "LONG":
            return self.mark_price <= self.stop_loss
        return self.mark_price >= self.stop_loss

    def _tp_hit(self) -> bool:
        if self.direction == "LONG":
            return self.mark_price >= self.take_profit
        return self.mark_price <= self.take_profit

    def _close(self, exit_price: float, reason: str) -> ClosedTrade:
        self.is_open = False
        closed_at    = datetime.now(timezone.utc)
        duration_s   = int((closed_at - self.opened_at).total_seconds())

        if self.direction == "LONG":
            raw_pnl = (exit_price - self.entry_price) * self.quantity
        else:
            raw_pnl = (self.entry_price - exit_price) * self.quantity

        exit_fee  = exit_price * self.quantity * self.FEE_RATE
        net_pnl   = raw_pnl - self._entry_fee - exit_fee

        notional  = self.entry_price * self.quantity
        pnl_pct   = net_pnl / notional if notional else 0.0

        # R:R (realised)
        risk_usdt = self._risk_per_unit * self.quantity
        rr = net_pnl / risk_usdt if risk_usdt != 0 else 0.0

        if net_pnl > 0:
            result = "WIN"
        elif net_pnl < 0:
            result = "LOSS"
        else:
            result = "BREAKEVEN"

        trade = ClosedTrade(
            position_id  = self.position_id,
            symbol       = self.symbol,
            direction    = self.direction,
            entry_price  = self.entry_price,
            exit_price   = round(exit_price, 2),
            quantity     = self.quantity,
            stop_loss    = self.stop_loss,
            take_profit  = self.take_profit,
            pnl          = round(net_pnl,   4),
            pnl_pct      = round(pnl_pct,   6),
            rr           = round(rr,         3),
            result       = result,
            opened_at    = self.opened_at.isoformat(),
            closed_at    = closed_at.isoformat(),
            duration_s   = duration_s,
            close_reason = reason,
            confidence   = self.confidence,
            regime       = self.regime,
            oi_delta     = self.oi_delta,
            funding_rate = self.funding_rate,
        )

        logger.info(
            f"PaperPosition closed | id={self.position_id} "
            f"reason={reason} exit={exit_price:.2f} "
            f"pnl={net_pnl:+.2f} U rr={rr:.2f} → {result}"
        )
        return trade
