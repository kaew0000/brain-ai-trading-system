"""
Paper Trading: Execution Engine

Routes ConfidenceResult decisions through PaperAccount + PaperPosition.
Exposes the same interface as TradeManager so main.py can swap it in.

Usage
-----
    from paper.paper_execution import PaperExecutionEngine
    engine = PaperExecutionEngine()
    result = engine.execute(decision, balance=account.balance, risk_pct=0.01)
    metrics = engine.get_metrics()
"""

from __future__ import annotations

import math
import threading

from config.settings import settings
from paper.paper_account import PaperAccount
from paper.paper_position import PaperPosition, ClosedTrade
from utils.logger import get_logger

logger = get_logger(__name__)

# Fee already baked into PaperPosition; this is for metrics display only
_FEE_RATE = PaperPosition.FEE_RATE


class PaperExecutionEngine:
    """
    Simulated execution layer.

    Accepts a ConfidenceResult (or any object with the fields below)
    and routes it through PaperAccount / PaperPosition.

    Required fields on `decision` object
    ------------------------------------
    action        : str   — "LONG" | "SHORT"
    direction     : str
    entry_price   : float
    stop_loss     : float
    take_profit   : float
    confidence    : int   — 0-100
    regime        : str
    oi_delta      : float
    funding_rate  : float
    """

    def __init__(
        self,
        account:        PaperAccount | None = None,
        starting_usdt:  float = 1_000.0,
        max_open:       int   = 1,          # only 1 position at a time (same as live)
        timeout_bars:   int | None = None,  # see PaperPosition.TIMEOUT_BARS docstring
    ) -> None:
        self.account   = account or PaperAccount(balance=starting_usdt)
        self.max_open  = max_open
        self._timeout_bars = timeout_bars
        self._lock     = threading.Lock()
        self._open:    list[PaperPosition] = []
        self._closed:  list[ClosedTrade]   = []

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def open_positions(self) -> list[PaperPosition]:
        """Read-only snapshot of currently open positions. Additive —
        existing callers that never used this are unaffected."""
        with self._lock:
            return list(self._open)

    @property
    def closed_trades(self) -> list[ClosedTrade]:
        """Read-only snapshot of all closed trades this session.
        Additive — existing callers that never used this are unaffected."""
        with self._lock:
            return list(self._closed)

    # ── State persistence (V16 Phase 4C §49 — TrainingLaneRunner restore-on-restart) ─
    # Deliberately does NOT include self._closed (this session's in-memory
    # closed-trade cache) — the durable record of every closed trade
    # already lives in research/dataset_builder.py's captured rows
    # regardless of this engine's own in-memory history, so restoring
    # _closed here would be redundant, not a source of truth. What DOES
    # need restoring is the account and any still-OPEN position — those
    # would otherwise silently vanish (and that trade's eventual outcome
    # would never get captured at all) on every process restart.

    def to_state_dict(self) -> dict:
        with self._lock:
            return {
                "account":   self.account.to_state_dict(),
                "positions": [p.to_state_dict() for p in self._open],
            }

    @classmethod
    def from_state_dict(
        cls, state: dict, max_open: int = 1, timeout_bars: int | None = None,
    ) -> "PaperExecutionEngine":
        """Reconstructs an engine from to_state_dict()'s output. Never
        raises: an account that fails to restore falls back to
        PaperAccount's own from_state_dict() defensiveness; any single
        position that fails to restore is logged and skipped (not fatal
        to the rest of the restore) — matches this whole subsystem's
        established "a restore hiccup should degrade, never crash"
        posture.

        `timeout_bars` is the caller's *current* calibrated value (e.g.
        TrainingLaneRunner recomputes it from its own poll interval on
        every boot) — used as the fallback for any restored position
        whose own saved state predates this fix and has no
        "timeout_bars" of its own. See PaperPosition.from_state_dict's
        `default_timeout_bars`."""
        account = PaperAccount.from_state_dict(state.get("account") or {})
        engine = cls(account=account, max_open=max_open, timeout_bars=timeout_bars)
        for pos_state in state.get("positions") or []:
            try:
                engine._open.append(
                    PaperPosition.from_state_dict(
                        pos_state, default_timeout_bars=timeout_bars,
                    )
                )
            except Exception as exc:
                logger.error(
                    f"PaperExecutionEngine.from_state_dict: skipping one "
                    f"position that failed to restore: {exc}"
                )
        return engine

    def execute(self, decision, risk_pct: float = 0.01, symbol: str | None = None) -> dict:
        """
        Open a paper position from a decision object.

        `symbol` lets a caller open a position for a symbol other than the
        globally-configured `settings.SYMBOL` — added for
        TrainingLaneRunner's multi-symbol rotation mode (V16 Phase 4C
        Track C), so a single PaperExecutionEngine/PaperAccount can hold
        positions across different symbols over its lifetime rather than
        being permanently tied to one. Defaults to `settings.SYMBOL` when
        omitted, so every pre-existing caller (execution/execution_factory.py's
        whole-bot EXECUTION_MODE=paper wiring) keeps its exact current
        behavior unchanged.

        Note: the 0.001 minimum-quantity floor below is a generic safety
        floor, not a real per-symbol exchange minimum (no per-symbol
        min-qty lookup exists in this codebase to consult — see
        PATCH_NOTES.md for this phase). Fine for this engine's purpose
        (paper/training data, not real order placement), but not a
        substitute for real exchange filters if this engine is ever used
        somewhere that matters.

        Returns a result dict (mirrors TradeManager.execute_trade() shape).
        """
        with self._lock:
            if decision.action not in ("LONG", "SHORT"):
                return {"success": False, "reason": f"action={decision.action} – skip"}

            if len(self._open) >= self.max_open:
                return {"success": False, "reason": "max_open positions reached"}

            entry  = float(decision.entry_price)
            sl     = float(decision.stop_loss)
            tp     = float(decision.take_profit)
            bal    = self.account.balance

            # Quantity = (balance × risk_pct) / |entry - SL| per unit
            risk_distance = abs(entry - sl)
            if risk_distance < 1e-8:
                return {"success": False, "reason": "entry==SL — degenerate levels"}

            risk_usdt = bal * risk_pct
            quantity  = round(risk_usdt / risk_distance, 6)
            quantity  = max(quantity, 0.001)          # generic min-qty floor — see execute()'s docstring

            notional = entry * quantity
            if not self.account.reserve_margin(notional):
                return {"success": False, "reason": "insufficient margin"}

            pos = PaperPosition(
                symbol       = symbol or settings.SYMBOL,
                direction    = decision.action,
                entry_price  = entry,
                stop_loss    = sl,
                take_profit  = tp,
                quantity     = quantity,
                leverage     = self.account.leverage,
                confidence   = int(getattr(decision, "confidence", 0)),
                regime       = str(getattr(decision, "regime",       "")),
                oi_delta     = float(getattr(decision, "oi_delta",     0.0)),
                funding_rate = float(getattr(decision, "funding_rate", 0.0)),
                timeout_bars = self._timeout_bars,
            )
            self._open.append(pos)

            return {
                "success":     True,
                "position_id": pos.position_id,
                "direction":   pos.direction,
                "entry_price": pos.entry_price,
                "stop_loss":   pos.stop_loss,
                "take_profit": pos.take_profit,
                "quantity":    pos.quantity,
                "notional":    round(notional, 2),
                "margin_used": round(notional / self.account.leverage, 2),
            }

    def tick(self, mark_price: float) -> list[ClosedTrade]:
        """
        Feed a new mark price.  Closes any SL/TP-hit positions.
        Returns list of ClosedTrade objects (may be empty).
        """
        closed_this_tick: list[ClosedTrade] = []

        with self._lock:
            still_open: list[PaperPosition] = []
            total_unrealised = 0.0

            for pos in self._open:
                ct = pos.update_mark(mark_price)
                if ct is not None:
                    # Position closed
                    self.account.release_margin(pos.notional)
                    self.account.realise_pnl(ct.pnl)
                    self._closed.append(ct)
                    closed_this_tick.append(ct)
                else:
                    still_open.append(pos)
                    total_unrealised += pos.unrealised_pnl

            self._open = still_open
            self.account.update_unrealised(total_unrealised)

        return closed_this_tick

    def close_all(self, mark_price: float) -> list[ClosedTrade]:
        """Force-close all open positions (e.g. end of session)."""
        closed: list[ClosedTrade] = []
        with self._lock:
            for pos in self._open:
                ct = pos.close_manual(float(mark_price))
                self.account.release_margin(pos.notional)
                self.account.realise_pnl(ct.pnl)
                self._closed.append(ct)
                closed.append(ct)
            self._open = []
            self.account.update_unrealised(0.0)
        return closed

    # ── Metrics ───────────────────────────────────────────────────────────────

    def get_metrics(self) -> dict:
        """Return full performance metrics over all closed trades."""
        with self._lock:
            closed = list(self._closed)

        if not closed:
            return {
                "total_trades":    0,
                "wins":            0,
                "losses":          0,
                "win_rate":        0.0,
                "profit_factor":   0.0,
                "sharpe_ratio":    0.0,
                "expectancy":      0.0,
                "max_drawdown":    0.0,
                "max_drawdown_pct": 0.0,
                "total_pnl":       0.0,
                "avg_pnl":         0.0,
                "avg_win":         0.0,
                "avg_loss":        0.0,
                "avg_rr":          0.0,
                "best_trade":      0.0,
                "worst_trade":     0.0,
                "account":         self.account.to_dict(),
            }

        pnls   = [t.pnl for t in closed]
        wins   = [t for t in closed if t.result == "WIN"]
        losses = [t for t in closed if t.result == "LOSS"]

        total_pnl  = sum(pnls)
        gross_win  = sum(t.pnl for t in wins)
        gross_loss = abs(sum(t.pnl for t in losses))

        win_rate      = len(wins) / len(closed)
        profit_factor = round(gross_win / max(gross_loss, 1e-9), 4)

        avg_win  = gross_win  / max(len(wins),   1)
        avg_loss = gross_loss / max(len(losses), 1)
        expectancy = (win_rate * avg_win) - ((1 - win_rate) * avg_loss)

        # Sharpe (daily returns, annualised at 365)
        sharpe = _sharpe(pnls)

        # Max drawdown
        mdd, mdd_pct = _max_drawdown(pnls, self.account.balance - total_pnl)

        return {
            "total_trades":    len(closed),
            "wins":            len(wins),
            "losses":          len(losses),
            "win_rate":        round(win_rate,      4),
            "profit_factor":   profit_factor,
            "sharpe_ratio":    round(sharpe,        4),
            "expectancy":      round(expectancy,    4),
            "max_drawdown":    round(mdd,           4),
            "max_drawdown_pct": round(mdd_pct,      4),
            "total_pnl":       round(total_pnl,     4),
            "avg_pnl":         round(total_pnl / len(closed), 4),
            "avg_win":         round(avg_win,        4),
            "avg_loss":        round(avg_loss,       4),
            "avg_rr":          round(sum(t.rr for t in closed) / len(closed), 4),
            "best_trade":      round(max(pnls),      4),
            "worst_trade":     round(min(pnls),      4),
            "account":         self.account.to_dict(),
        }

    # ── State inspection ──────────────────────────────────────────────────────

    def get_open_positions(self) -> list[dict]:
        with self._lock:
            return [p.to_dict() for p in self._open]

    def get_closed_trades(self, limit: int = 200) -> list[dict]:
        with self._lock:
            return [t.to_dict() for t in self._closed[-limit:]]

    @property
    def trade_count(self) -> int:
        with self._lock:
            return len(self._closed)

    @property
    def has_open_position(self) -> bool:
        with self._lock:
            return bool(self._open)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sharpe(pnls: list[float], periods_per_year: float = 365.0) -> float:
    """Annualised Sharpe Ratio from a list of per-trade PnL values."""
    n = len(pnls)
    if n < 2:
        return 0.0
    mean = sum(pnls) / n
    variance = sum((x - mean) ** 2 for x in pnls) / (n - 1)
    std = math.sqrt(variance)
    if std < 1e-12:
        return 0.0
    return round((mean / std) * math.sqrt(periods_per_year), 4)


def _max_drawdown(pnls: list[float], starting_balance: float) -> tuple[float, float]:
    """
    Max drawdown in USDT and % from equity peak.
    starting_balance = account balance before the first trade.
    """
    equity = starting_balance
    peak   = equity
    max_dd = 0.0
    max_dd_pct = 0.0

    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        dd     = peak - equity
        dd_pct = dd / peak if peak > 0 else 0.0
        if dd > max_dd:
            max_dd     = dd
            max_dd_pct = dd_pct

    return max_dd, max_dd_pct
