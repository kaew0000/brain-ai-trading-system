"""system_health/recovery_engine.py — Automatic recovery actions"""
from __future__ import annotations
import threading
from datetime import datetime, timezone
from typing import Optional
from utils.logger import get_logger
logger = get_logger(__name__)

_COOLDOWN_S = 30.0

class RecoveryEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last: dict[str, datetime] = {}
        self._log: list[dict] = []

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
                jrn.update_trade_result(tid, "CANCELLED", 0.0, 0.0)
                self._record("recon_recovery", f"trade_id={tid}", "closed_ghost_row")
                logger.warning(f"Recon recovery: closed ghost journal trade #{tid}")
                return "closed_ghost_journal_row"
            return "no_safe_auto_action"
        except Exception as exc:
            logger.error(f"attempt_reconciliation_recovery failed: {exc}", exc_info=True)
            return f"error:{exc}"

_re: Optional[RecoveryEngine] = None
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
