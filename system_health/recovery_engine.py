"""system_health/recovery_engine.py — Automatic recovery actions"""
from __future__ import annotations
import threading
from datetime import datetime, timezone
from config.settings import settings
from utils.logger import get_logger
from execution.trade_lifecycle import CloseSource
logger = get_logger(__name__)

_COOLDOWN_S = 30.0

class RecoveryEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, datetime] = {}
        self._log: list[dict] = []
        # V16 BUG-LIVE-RISK-02: set when an exchange position is found with
        # no journal record of it (PRESENCE_MISMATCH, exchange side open).
        # Persists across reconciliation cycles until a human explicitly
        # calls acknowledge_orphaned_position() — see that method and
        # _protect_orphaned_exchange_position() below.
        self._orphan_hold: dict | None = None

    def _ok(self, key: str) -> bool:
        with self._lock:
            last = self._last.get(key)
            now = datetime.now(timezone.utc)
            if last and (now - last).total_seconds() < _COOLDOWN_S:
                return False
            self._last[key] = now
            return True

    def _record(self, action: str, target: str, result: str) -> None:
        with self._lock:
            self._log.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "action": action, "target": target, "result": result,
            })
            if len(self._log) > 200:
                self._log.pop(0)

    def get_attempt_log(self, limit: int = 50) -> list[dict]:
        with self._lock:
            return list(self._log[-limit:][::-1])

    def attempt_reconnect_data_provider(self, sys: dict) -> str:
        if not self._ok("data_provider"):
            return "skipped_cooldown"
        try:
            dp = sys.get("data_provider")
            if dp is None:
                self._record("reconnect_data_provider", "dp", "no_provider")
                return "no_provider"
            dp._sync_time_offset()
            dp.get_account_balance()
            self._record("reconnect_data_provider", "dp", "ok")
            return "ok"
        except Exception as exc:
            self._record("reconnect_data_provider", "dp", f"failed:{exc}")
            return f"failed:{exc}"

    def attempt_scheduler_restart(self, sys: dict, job_name: str) -> str:
        if not self._ok(f"scheduler:{job_name}"):
            return "skipped_cooldown"
        try:
            import schedule as _s
            found = any(job_name in str(j) for j in _s.jobs)
            result = "registered" if found else "missing"
            self._record("scheduler_check", job_name, result)
            return result
        except Exception as exc:
            self._record("scheduler_check", job_name, f"failed:{exc}")
            return f"failed:{exc}"

    def cleanup_stale_state(self, sys: dict) -> str:
        try:
            mt = sys.get("mission_tracker")
            mid = sys.get("current_mission_id")
            if mt is None or mid is None:
                return "nothing_to_clean"
            m = mt.get(mid)
            if m is not None and m.stage == "CLOSED":
                sys["current_mission_id"] = None
                self._record("cleanup_stale_state", "current_mission_id", "cleared")
                return "cleared"
            return "not_stale"
        except Exception as exc:
            self._record("cleanup_stale_state", "current_mission_id", f"failed:{exc}")
            return f"failed:{exc}"

    def attempt_reconciliation_recovery(self, event, sys: dict) -> str:
        try:
            if event.mismatch_type != "PRESENCE_MISMATCH":
                return f"no_auto_recovery_for:{event.mismatch_type}"
            ex = event.exchange_view
            bot = event.bot_view
            jv = event.journal_view
            if (ex.get("has_position") is False and bot.get("has_position") is False
                    and jv.get("has_position") is True):
                jrn = sys.get("journal_v2")
                tid = jv.get("trade_id")
                if not jrn or tid is None:
                    return "missing_journal_or_trade_id"
                # V16 Phase 4B Step 3D: routed through TradeLifecycle
                # (Part C/F: "Recovery must never update journal
                # directly. Recovery must call lifecycle."). jv (this
                # reconciliation check's own _read_journal() output) has
                # no symbol key — reconciliation is inherently scoped to
                # this bot's one configured symbol (same reasoning
                # applied to this exact code path in V16 Phase 4B
                # Step 3A), so settings.SYMBOL is the real value here,
                # not a fabricated placeholder.
                lifecycle = sys.get("trade_lifecycle")
                if lifecycle is not None:
                    from config.settings import settings
                    handle = lifecycle.request_exit(
                        settings.SYMBOL, CloseSource.RECONCILIATION,
                        "presence_mismatch_ghost_row", trade_id=tid,
                    )
                    if handle is not None:
                        lifecycle.exit_executing(handle)
                        lifecycle.exit_confirmed(handle, result="CANCELLED", exit_price=0.0, pnl=0.0)
                    else:
                        # Duplicate-close guard fired — already closed
                        # through the lifecycle by another path. Fall
                        # back to the direct write so this recovery
                        # action's own long-standing guarantee (a
                        # detected ghost row always gets cleared) isn't
                        # silently dropped.
                        jrn.update_trade_result(tid, "CANCELLED", 0.0, 0.0)
                else:
                    jrn.update_trade_result(tid, "CANCELLED", 0.0, 0.0)
                self._record("recon_recovery", f"trade_id={tid}", "closed_ghost_row")
                logger.warning(f"Recon recovery: closed ghost journal trade #{tid}")
                return "closed_ghost_journal_row"

            # V16 BUG-LIVE-RISK-02: the OPPOSITE case — a real exchange
            # position exists that the journal has no record of at all
            # (pre-existing position from before this bot session, or one
            # opened outside the bot's lifecycle). Previously fell through
            # to "no_safe_auto_action" with no SL/TP and no alert beyond a
            # log line. Now: auto-place a protective SL sized off the
            # configured risk %, AND hold all new entries until a human
            # acknowledges — see _protect_orphaned_exchange_position().
            if ex.get("has_position") is True and jv.get("has_position") is False:
                return self._protect_orphaned_exchange_position(sys)

            return "no_safe_auto_action"
        except Exception as exc:
            logger.error(f"attempt_reconciliation_recovery failed: {exc}", exc_info=True)
            return f"error:{exc}"

    # ── V16 BUG-LIVE-RISK-02: orphaned exchange position ────────────────────

    def _protect_orphaned_exchange_position(self, sys: dict) -> str:
        """
        Real exchange position, nothing in the journal. Auto-places a
        protective SL sized off settings.RISK_PER_TRADE_MAX (same risk-%
        convention TradeManager.calculate_position_size() already uses for
        new trades) and sets a manual hold on RiskEngine so no new entries
        are attempted until acknowledge_orphaned_position() is called.

        Idempotent within a process: if a hold is already active for this
        symbol, does not attempt to place a second SL (avoids stacking
        reduceOnly orders every time this fires) but still re-confirms the
        hold is in place.
        """
        dp = sys.get("data_provider")
        tm = sys.get("trade_manager")
        risk = sys.get("risk_engine")
        if dp is None or tm is None:
            return "missing_data_provider_or_trade_manager"

        try:
            pos = dp.get_position_info()
        except Exception as exc:
            logger.error(f"Orphan-protect: could not re-query position: {exc}")
            return f"error:{exc}"

        if pos is None:
            # Closed between the reconciliation read and now — nothing to protect.
            return "position_no_longer_open"

        symbol = pos.get("symbol")
        already_held = self._orphan_hold is not None and self._orphan_hold.get("symbol") == symbol
        if already_held:
            # Re-confirm the hold is still in place (e.g. risk_engine was
            # replaced/restarted) without re-placing an SL.
            if risk is not None and not risk.has_manual_hold():
                risk.set_manual_hold(self._orphan_hold.get("reason", "Orphaned exchange position — awaiting acknowledgement"))
            self._record("orphan_protect", symbol or "?", "already_held")
            return "orphan_already_held"

        direction   = pos.get("side")
        qty         = pos.get("positionAmt")
        entry_price = pos.get("entryPrice")

        sl_price: float | None = None
        sl_order = None
        try:
            balance     = dp.get_account_balance()
            risk_pct    = getattr(settings, "RISK_PER_TRADE_MAX", 0.01)
            risk_amount = balance * risk_pct
            if qty and qty > 0:
                sl_dist  = risk_amount / qty
                sl_price = (entry_price - sl_dist) if direction == "LONG" else (entry_price + sl_dist)
                from execution.trade_manager import new_client_order_id
                sl_order = tm.place_stop_loss(
                    direction, qty, sl_price,
                    client_order_id=new_client_order_id("ORPHANSL"),
                )
        except Exception as exc:
            logger.error(f"Orphan-protect: SL placement failed: {exc}", exc_info=True)
            sl_order = None

        sl_placed = sl_order is not None
        reason = (
            f"Unprotected exchange position detected: {direction} {qty} "
            f"{symbol} @ {entry_price} — "
            + ("protective SL placed automatically" if sl_placed
               else "AUTO SL PLACEMENT FAILED, position still naked")
            + " | acknowledge via acknowledge_orphaned_position() "
              "(or POST /api/system/reconciliation/acknowledge) once resolved"
        )

        self._orphan_hold = {
            "symbol": symbol, "direction": direction, "qty": qty,
            "entry_price": entry_price, "sl_price": sl_price,
            "sl_placed": sl_placed,
            "detected_at": datetime.now(timezone.utc).isoformat(),
            "reason": reason,
        }

        if risk is not None:
            risk.set_manual_hold(reason)

        try:
            bus = sys.get("event_bus")
            if bus is not None:
                bus.publish(
                    "RECOVERY_ENGINE", "ORPHAN_POSITION_HOLD", reason,
                    severity="critical", payload=dict(self._orphan_hold),
                )
        except Exception as exc:
            logger.debug(f"Orphan-protect: event publish failed: {exc}")

        self._record("orphan_protect", symbol or "?", f"sl_placed={sl_placed}")
        logger.critical(reason)
        return "orphan_sl_placed_and_holding" if sl_placed else "orphan_sl_failed_still_holding"

    def get_orphan_hold(self) -> dict | None:
        return dict(self._orphan_hold) if self._orphan_hold is not None else None

    def acknowledge_orphaned_position(self, sys: dict | None = None, operator: str = "unknown") -> str:
        """
        Clear the orphan hold and resume normal trading. Intended to be
        called explicitly by a human (dashboard 'acknowledge' action /
        POST /api/system/reconciliation/acknowledge) after they've
        confirmed the position is protected/handled — this method itself
        does not re-verify exchange state, by design: acknowledgement is a
        human judgment call, not an automatic one.
        """
        if self._orphan_hold is None:
            return "no_hold_active"
        cleared = dict(self._orphan_hold)
        cleared["acknowledged_at"] = datetime.now(timezone.utc).isoformat()
        cleared["acknowledged_by"] = operator
        self._orphan_hold = None

        risk = sys.get("risk_engine") if sys is not None else None
        if risk is not None:
            risk.clear_manual_hold()

        self._record("orphan_hold_acknowledged", cleared.get("symbol", "?"), f"by={operator}")
        logger.warning(f"Orphaned-position hold acknowledged and cleared by {operator}")
        return "cleared"

_re: RecoveryEngine | None = None
_re_lock = threading.Lock()

def get_recovery_engine() -> RecoveryEngine:
    global _re
    if _re is None:
        with _re_lock:
            if _re is None:
                _re = RecoveryEngine()
    return _re

def reset_recovery_engine() -> RecoveryEngine:
    global _re
    with _re_lock:
        _re = RecoveryEngine()
    return _re
