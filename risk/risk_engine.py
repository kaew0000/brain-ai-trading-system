"""
Risk Layer: Risk Engine

Controls
--------
  - Max daily loss 3 %
  - Max consecutive losses 3
  - Dynamic risk % (scales down on losing streaks AND on high volatility)
  - Dynamic leverage (scales down on high volatility)
  - disable_trading_today() resets at midnight UTC

All checks must pass before TradeManager.execute_trade() is called.

P1-B1 (volatility risk)
------------------------
get_risk_pct() and the new get_leverage() both accept an optional
`atr_pct` — the normalized ATR (ATR / close price) for the current
candle, already computed every cycle by RegimeEngine.classify() as
RegimeResult.atr_normalized (regime/regime_engine.py). Passing it in is
the caller's responsibility; RiskEngine has no market-data access of its
own and does not compute ATR itself — avoiding a duplicate ATR
computation here rather than reusing RegimeEngine's.

`atr_pct` defaults to None everywhere, which reproduces the pre-P1-B1
behavior exactly (volatility factor = 1.0, no effect) — existing callers
that don't pass it (including the 18-odd direct RiskEngine(...) call sites
across tests/test_agents.py and tests/test_execution.py) are unaffected.
"""

from __future__ import annotations

from datetime import datetime, date, timezone

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)


class RiskEngine:
    """
    Stateful (within session) risk gate.

    Parameters
    ----------
    journal : TradeJournal
        Used to read today's PnL and consecutive loss count.
    """

    def __init__(self, journal) -> None:
        self.journal               = journal
        self._disabled_today: bool = False
        self._disable_date: date | None = None
        logger.info("RiskEngine ready")

    # ── Day boundary ──────────────────────────────────────────────────────

    def _reset_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._disable_date is not None and self._disable_date != today:
            self._disabled_today = False
            self._disable_date   = None
            logger.info("Risk state reset for new UTC day")

    def disable_trading_today(self, reason: str) -> None:
        self._disabled_today = True
        self._disable_date   = datetime.now(timezone.utc).date()
        logger.warning(f"TRADING DISABLED TODAY | {reason}")

    # ── Individual checks ─────────────────────────────────────────────────

    def check_daily_loss(self, balance: float) -> tuple[bool, str]:
        pnl     = self.journal.get_today_pnl()
        max_loss = balance * settings.MAX_DAILY_LOSS
        if pnl < -max_loss:
            reason = (
                f"Daily loss limit: pnl={pnl:.2f} U "
                f"limit={-max_loss:.2f} U"
            )
            return False, reason
        return True, ""

    def check_consecutive_losses(self) -> tuple[bool, str]:
        streak = self.journal.get_consecutive_losses()
        if streak >= settings.MAX_CONSECUTIVE_LOSSES:
            return False, f"Consecutive losses: {streak}/{settings.MAX_CONSECUTIVE_LOSSES}"
        return True, ""

    # ── Volatility scaling (P1-B1) ──────────────────────────────────────────

    @staticmethod
    def _volatility_factor(atr_pct: float | None) -> float:
        """
        1.0 when atr_pct is unknown or at/below the volatile threshold.
        Below that, scales linearly down to VOLATILITY_RISK_FLOOR as
        atr_pct grows — e.g. at 2x the threshold, factor is halfway
        between 1.0 and the floor; never goes below the floor itself.
        """
        threshold = settings.VOLATILITY_RISK_THRESHOLD
        if atr_pct is None or atr_pct <= threshold or threshold <= 0:
            return 1.0
        raw = threshold / atr_pct
        return max(settings.VOLATILITY_RISK_FLOOR, min(1.0, raw))

    # ── Dynamic risk % ────────────────────────────────────────────────────

    def get_risk_pct(self, balance: float, atr_pct: float | None = None) -> float:
        """
        Scale down risk when losing, and further scale down in high
        volatility.
          streak ≥ 2            → MIN risk (volatility factor still applies,
                                   but MIN is already the floor so it's a no-op)
          daily loss > 50 % cap → MIN risk (same as above)
          normal                → MAX risk × volatility factor, never below MIN
        """
        streak  = self.journal.get_consecutive_losses()
        pnl     = self.journal.get_today_pnl()
        max_loss = balance * settings.MAX_DAILY_LOSS

        if streak >= 2:
            base = settings.RISK_PER_TRADE_MIN
        else:
            used = abs(min(pnl, 0)) / max(max_loss, 1e-9)
            base = settings.RISK_PER_TRADE_MIN if used > 0.50 else settings.RISK_PER_TRADE_MAX

        scaled = base * self._volatility_factor(atr_pct)
        return max(settings.RISK_PER_TRADE_MIN, scaled)

    def get_leverage(self, atr_pct: float | None = None) -> int:
        """
        Volatility-scaled leverage. Base is settings.LEVERAGE; scales down
        the same way as risk-per-trade, floored at 1x (Binance's own
        minimum — not configurable, it's an exchange constraint rather
        than a tunable risk parameter).
        """
        lev = round(settings.LEVERAGE * self._volatility_factor(atr_pct))
        return max(1, lev)

    # ── Gate ─────────────────────────────────────────────────────────────

    def can_trade(self, balance: float) -> tuple[bool, str]:
        """
        Full risk gate.  Returns (ok, reason_string).
        Side-effects: disables today when limit is hit.
        """
        self._reset_if_new_day()

        if self._disabled_today:
            return False, "Trading disabled for today"

        ok, reason = self.check_daily_loss(balance)
        if not ok:
            self.disable_trading_today(reason)
            return False, reason

        ok, reason = self.check_consecutive_losses()
        if not ok:
            self.disable_trading_today(reason)
            return False, reason

        return True, ""

    # ── Report ────────────────────────────────────────────────────────────

    def report(self, balance: float, atr_pct: float | None = None) -> dict:
        self._reset_if_new_day()
        today      = self.journal.get_daily_stats()
        streak     = self.journal.get_consecutive_losses()
        ok, reason = self.can_trade(balance)
        return {
            "can_trade":          ok,
            "block_reason":       reason,
            "disabled_today":     self._disabled_today,
            "consecutive_losses": streak,
            "today_pnl":          today.get("total_pnl",    0.0),
            "today_trades":       today.get("total_trades",  0),
            "today_win_rate":     today.get("win_rate",      0.0),
            "max_daily_loss_u":   round(balance * settings.MAX_DAILY_LOSS, 2),
            "dynamic_risk_pct":   self.get_risk_pct(balance, atr_pct),
            # P1-B1 additions. New keys only — every key above is unchanged,
            # so existing readers of this dict (agents/risk_manager.py) keep
            # working without modification.
            "dynamic_leverage":   self.get_leverage(atr_pct),
            "atr_pct":            atr_pct,
            "volatility_factor":  self._volatility_factor(atr_pct),
        }
