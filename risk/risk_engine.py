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
        # V16 BUG-LIVE-RISK-03: which check set _disabled_today, so an
        # override can punch through the sticky latch specifically for
        # "consecutive_losses" without also bypassing "daily_loss" (a
        # separate, more urgent protection). None when _disabled_today is
        # False. See override_next_trade_despite_streak() below.
        self._disabled_by: str | None = None
        # V16 BUG-LIVE-RISK-02: manual hold, distinct from _disabled_today.
        # _disabled_today auto-clears at the next UTC day boundary (see
        # _reset_if_new_day) — appropriate for daily-loss/consecutive-loss
        # limits, but wrong for "an exchange position was found with no
        # protective SL/TP and no journal record of it" (RecoveryEngine,
        # system_health/recovery_engine.py): that condition must keep
        # blocking new entries across day boundaries until a human
        # explicitly acknowledges it, not just until midnight UTC.
        self._manual_hold_reason: str | None = None
        # V16 BUG-LIVE-RISK-03/04: one-shot operator override for a stale/
        # confirmed-legitimate consecutive-loss block. See
        # override_next_trade_despite_streak()'s docstring for why this
        # exists and why it's deliberately one-shot rather than a
        # persistent disable. Restored from the journal's persisted state
        # (if any) rather than starting unarmed every time -- otherwise a
        # bot restart (routine during normal dev/test iteration) would
        # silently discard an operator's already-confirmed override with
        # no indication anything was lost, forcing a re-run of the same
        # override call after every restart.
        #
        # The isinstance(..., str) check (not just "is journal missing the
        # method") matters: most of this project's own RiskEngine tests
        # construct it with a bare, unconfigured MagicMock() as the
        # journal, and MagicMock auto-creates any attribute accessed on
        # it -- getattr(mock, "get_risk_override", None) would return a
        # MagicMock (truthy), and calling it returns another MagicMock
        # (also truthy, not None), which would silently arm a fake
        # override on construction for every single one of those tests.
        # Requiring the restored value to actually be a str is what makes
        # this safe against that without requiring every existing test
        # fixture across the suite to be updated.
        get_persisted = getattr(journal, "get_risk_override", None)
        restored = get_persisted() if get_persisted else None
        self._consecutive_loss_override_reason = restored if isinstance(restored, str) else None
        if self._consecutive_loss_override_reason is not None:
            logger.critical(
                "RISK OVERRIDE RESTORED from previous session: "
                f"{self._consecutive_loss_override_reason}"
            )
        logger.info("RiskEngine ready")

    # ── Manual hold (V16 BUG-LIVE-RISK-02) ──────────────────────────────────

    def set_manual_hold(self, reason: str) -> None:
        """Block can_trade() until clear_manual_hold() is called explicitly.
        Does NOT auto-clear at the UTC day boundary — use disable_trading_today()
        for that instead. Calling this again while already held overwrites the
        reason (last caller wins) without needing to be cleared first."""
        self._manual_hold_reason = reason
        logger.critical(f"TRADING MANUALLY HELD | {reason}")

    def clear_manual_hold(self) -> None:
        if self._manual_hold_reason is not None:
            logger.warning(f"Manual trading hold cleared (was: {self._manual_hold_reason})")
        self._manual_hold_reason = None

    def has_manual_hold(self) -> bool:
        return self._manual_hold_reason is not None

    def manual_hold_reason(self) -> str | None:
        return self._manual_hold_reason

    # ── Consecutive-loss override (V16 BUG-LIVE-RISK-03) ────────────────────
    # Bug context (2026-08-31): check_consecutive_losses() reads the LIVE
    # lane's last-20-trades streak straight from the journal every call --
    # it isn't a resettable in-memory counter. A genuinely stale block
    # (e.g. the last LIVE trade was 8 days ago and happened to be the 3rd
    # loss in a row, with nothing since to ever produce a new LIVE win and
    # naturally clear it) has no way to resolve on its own: disable_trading_
    # today()'s UTC-midnight reset doesn't help, because the very next
    # can_trade() call just recomputes the same streak from history and
    # re-blocks immediately. This is a deliberately narrow, one-shot escape
    # hatch for exactly that situation -- not a way to disable the gate.

    def _persist_override(self, reason: str) -> None:
        """Best-effort: write-through to the journal so the override
        survives a restart. Guarded the same way as the __init__ restore
        above, for the same reason (tests constructing RiskEngine with a
        minimal stub journal that doesn't implement this)."""
        save = getattr(self.journal, "save_risk_override", None)
        if save:
            save(reason)

    def _clear_persisted_override(self) -> None:
        clear = getattr(self.journal, "clear_risk_override", None)
        if clear:
            clear()

    def override_next_trade_despite_streak(self, reason: str) -> None:
        """Bypasses check_consecutive_losses() for exactly the next
        can_trade() call, then disarms itself automatically -- it does
        NOT silently disable the gate indefinitely, and does NOT touch
        check_daily_loss() (a real-money percentage-of-balance limit,
        a separate and more urgent protection) or _manual_hold_reason
        (an operator-imposed hold for a *different* reason, e.g.
        RecoveryEngine's orphaned-position hold -- this must never
        accidentally clear that too).

        Persisted via the journal (V16 BUG-LIVE-RISK-04) so it survives
        a bot restart between arming it and the next actual can_trade()
        opportunity -- still genuinely one-shot, just no longer scoped
        to "one process lifetime".

        Call this only after reviewing why the streak tripped (e.g. via
        this class's own report()) and confirming the block no longer
        reflects current conditions. If the resulting trade also loses,
        the very next can_trade() call re-blocks normally -- this is a
        single "let one probe trade through" lever, not a reset.
        """
        self._consecutive_loss_override_reason = reason
        self._persist_override(reason)
        logger.critical(
            "RISK OVERRIDE ARMED: consecutive-loss gate will be bypassed "
            f"for exactly the next can_trade() check | reason={reason}"
        )

    def clear_consecutive_loss_override(self) -> None:
        """Disarm an override before it's consumed, if the operator
        changes their mind."""
        if self._consecutive_loss_override_reason is not None:
            logger.warning(
                "Consecutive-loss override cleared before use (was: "
                f"{self._consecutive_loss_override_reason})"
            )
        self._consecutive_loss_override_reason = None
        self._clear_persisted_override()

    def has_consecutive_loss_override(self) -> bool:
        return self._consecutive_loss_override_reason is not None

    def consecutive_loss_override_reason(self) -> str | None:
        return self._consecutive_loss_override_reason

    # ── Day boundary ──────────────────────────────────────────────────────

    def _reset_if_new_day(self) -> None:
        today = datetime.now(timezone.utc).date()
        if self._disable_date is not None and self._disable_date != today:
            self._disabled_today = False
            self._disable_date   = None
            self._disabled_by    = None
            logger.info("Risk state reset for new UTC day")

    def disable_trading_today(self, reason: str, cause: str | None = None) -> None:
        """cause: optional short tag ("daily_loss" / "consecutive_losses")
        recorded alongside the block so a later override can target the
        specific check that tripped -- see can_trade()'s _disabled_today
        branch and override_next_trade_despite_streak() above. Existing
        callers that don't pass it (external callers outside this class,
        if any) keep working identically; cause just stays None."""
        self._disabled_today = True
        self._disable_date   = datetime.now(timezone.utc).date()
        self._disabled_by    = cause
        logger.warning(f"TRADING DISABLED TODAY | {reason}")

    # ── Individual checks ─────────────────────────────────────────────────

    def check_daily_loss(self, balance: float) -> tuple[bool, str]:
        # execution_lane="LIVE": same rationale as check_consecutive_losses
        # below -- background TRAINING/PAPER-lane PnL swings (that lane's
        # $100 auto-training balance busting/resetting) must never gate
        # real capital's daily-loss limit.
        pnl     = self.journal.get_today_pnl(execution_lane="LIVE")
        max_loss = balance * settings.MAX_DAILY_LOSS
        if pnl < -max_loss:
            reason = (
                f"Daily loss limit: pnl={pnl:.2f} U "
                f"limit={-max_loss:.2f} U"
            )
            return False, reason
        return True, ""

    def check_consecutive_losses(self) -> tuple[bool, str]:
        # execution_lane="LIVE": see journal_v2.get_consecutive_losses()'s
        # docstring -- the always-on background training lane's frequent,
        # expected losses must never gate real capital.
        streak = self.journal.get_consecutive_losses(execution_lane="LIVE")
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
        streak  = self.journal.get_consecutive_losses(execution_lane="LIVE")
        pnl     = self.journal.get_today_pnl(execution_lane="LIVE")
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

        if self._manual_hold_reason is not None:
            return False, self._manual_hold_reason

        if self._disabled_today:
            # V16 BUG-LIVE-RISK-03: an armed override must be able to punch
            # through this sticky same-session latch, not just a *fresh*
            # check_consecutive_losses() call below -- otherwise the
            # override would only ever work on the very first can_trade()
            # call after a process restart (before _disabled_today gets
            # set again), which defeats the point of it being callable at
            # any time via the dashboard/API. Only bypasses when the latch
            # was specifically set *by* the consecutive-loss check -- a
            # daily_loss-caused latch is untouched by this override.
            if (self._disabled_by == "consecutive_losses"
                    and self._consecutive_loss_override_reason is not None):
                override_reason = self._consecutive_loss_override_reason
                self._consecutive_loss_override_reason = None   # one-shot: consume now
                self._clear_persisted_override()
                self._disabled_today = False
                self._disable_date   = None
                self._disabled_by    = None
                logger.critical(
                    "RISK OVERRIDE CONSUMED: bypassing latched consecutive-"
                    f"loss block | override_reason={override_reason}"
                )
                return True, ""
            return False, "Trading disabled for today"

        ok, reason = self.check_daily_loss(balance)
        if not ok:
            self.disable_trading_today(reason, cause="daily_loss")
            return False, reason

        ok, reason = self.check_consecutive_losses()
        if not ok:
            if self._consecutive_loss_override_reason is not None:
                override_reason = self._consecutive_loss_override_reason
                self._consecutive_loss_override_reason = None   # one-shot: consume now
                self._clear_persisted_override()
                logger.critical(
                    f"RISK OVERRIDE CONSUMED: bypassing consecutive-loss "
                    f"block ({reason}) | override_reason={override_reason}"
                )
                return True, ""
            self.disable_trading_today(reason, cause="consecutive_losses")
            return False, reason

        return True, ""

    # ── Report ────────────────────────────────────────────────────────────

    def report(self, balance: float, atr_pct: float | None = None) -> dict:
        self._reset_if_new_day()
        # execution_lane="LIVE": this dict's own can_trade/dynamic_risk_pct
        # fields are already computed from LIVE-only figures (see
        # check_daily_loss/check_consecutive_losses/get_risk_pct above) --
        # today_pnl/today_trades/today_win_rate must match the same scope,
        # or this report would show e.g. "today_pnl: -500" (all lanes)
        # right next to "can_trade: True" with no visible reason why the
        # daily-loss gate didn't trip. For an all-lanes activity view, see
        # api/app.py's or main.py's own direct journal.get_daily_stats()
        # calls, which are unrelated to this risk report.
        today      = self.journal.get_daily_stats(execution_lane="LIVE")
        streak     = self.journal.get_consecutive_losses(execution_lane="LIVE")
        # Captured before can_trade() below, since can_trade() consumes a
        # one-shot override as a side effect -- this reflects "was an
        # override present going into this check" rather than "is one
        # still armed after" (which would always show False the instant
        # it's used).
        override_armed_before = self._consecutive_loss_override_reason
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
            # V16 BUG-LIVE-RISK-02 additions. New keys only — every key
            # above is unchanged, so existing readers keep working.
            "manual_hold":        self._manual_hold_reason is not None,
            "manual_hold_reason": self._manual_hold_reason,
            # V16 BUG-LIVE-RISK-03 additions. New keys only.
            "consecutive_loss_override_armed":  override_armed_before is not None,
            "consecutive_loss_override_reason": override_armed_before,
        }
