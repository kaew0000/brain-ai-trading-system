"""system_health/reconciliation.py — Position reconciliation (Exchange/Bot/Journal)"""
from __future__ import annotations
import threading
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from utils.logger import get_logger
from events.event_bus import get_event_bus
logger = get_logger(__name__)

@dataclass
class ReconciliationEvent:
    id: str; timestamp: str; mismatch_type: str
    exchange_view: dict; journal_view: dict; bot_view: dict
    severity: str; detail: str
    recovery_attempted: bool = False; recovery_result: str | None = None
    def to_dict(self) -> dict: return asdict(self)

class ReconciliationEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buf: list[ReconciliationEvent] = []
        self._last_run: str | None = None
        self._last_result: str | None = None
        # Signature (mismatch_type, severity, detail) of the last mismatch
        # we actually published/logged/attempted-recovery-for. Used to
        # suppress re-firing the *identical* mismatch every cycle while a
        # pre-existing condition (e.g. a startup PRESENCE_MISMATCH on an
        # exchange position opened before this bot session) remains open.
        # Reset to None once the system goes flat/clean, so a *new*
        # mismatch — even of the same type — always fires fresh.
        self._last_fired_sig: tuple | None = None
        self._suppressed_repeat_count: int = 0

    def run(self, sys: dict) -> ReconciliationEvent | None:
        try:
            ex = self._read_exchange(sys)
            bot = self._read_bot(sys, ex)
            jv = self._read_journal(sys)
            self._last_run = datetime.now(timezone.utc).isoformat()
            mt, sev, detail = self._classify(ex, jv, bot)
            if mt is None:
                self._last_result = "OK"
                # Condition cleared — next mismatch (even if same type as
                # before) should fire fresh rather than staying suppressed.
                self._last_fired_sig = None
                self._suppressed_repeat_count = 0
                return None
            self._last_result = "MISMATCH"

            sig = (mt, sev, detail)
            if sig == self._last_fired_sig:
                # Identical mismatch to the one already reported — don't
                # re-publish/re-log/re-attempt-recovery every cycle. Recovery
                # already returned its verdict once; nothing changed, so
                # re-asking gives the same answer for the cost of an exchange
                # round trip plus log noise every 60s for as long as the
                # position stays open.
                self._suppressed_repeat_count += 1
                return None

            evt = ReconciliationEvent(
                id=uuid.uuid4().hex[:12], timestamp=self._last_run,
                mismatch_type=mt, exchange_view=ex, journal_view=jv,
                bot_view=bot, severity=sev, detail=detail,
            )
            try:
                bus = sys.get("event_bus") or get_event_bus()
                bus.publish("RISK_MANAGER", "RECONCILIATION_MISMATCH", detail,
                            severity=sev, payload=evt.to_dict())
            except Exception as exc:
                logger.debug(f"Recon publish failed: {exc}")
            try:
                from system_health.recovery_engine import get_recovery_engine
                res = get_recovery_engine().attempt_reconciliation_recovery(evt, sys)
                evt.recovery_attempted = True; evt.recovery_result = res
            except Exception as exc:
                evt.recovery_attempted = True; evt.recovery_result = f"error:{exc}"
            with self._lock:
                self._buf.append(evt)
                if len(self._buf) > 200: self._buf.pop(0)
            logger.warning(f"Recon MISMATCH | {mt} {sev} | {detail}")
            self._last_fired_sig = sig
            self._suppressed_repeat_count = 0
            return evt
        except Exception as exc:
            logger.error(f"ReconciliationEngine.run failed: {exc}", exc_info=True)
            return None

    def get_recent(self, limit: int = 50) -> list[dict]:
        with self._lock: return [e.to_dict() for e in self._buf[-limit:][::-1]]

    def status(self) -> dict:
        return {"last_run": self._last_run, "last_result": self._last_result,
                "event_count": len(self._buf),
                "suppressed_repeat_count": self._suppressed_repeat_count}

    def _read_exchange(self, sys: dict) -> dict:
        dp = sys.get("data_provider")
        if dp is None: return {"has_position": None, "side": None, "qty": None, "source": "unavailable"}
        try:
            pos = dp.get_position_info()
            if pos is None: return {"has_position": False, "side": None, "qty": None, "source": "exchange"}
            return {"has_position": True, "side": pos.get("side"),
                    "qty": abs(float(pos.get("positionAmt", 0))), "source": "exchange"}
        except Exception as exc:
            return {"has_position": None, "side": None, "qty": None, "source": "error", "error": str(exc)}

    def _read_bot(self, sys: dict, exchange: dict) -> dict:
        pe = sys.get("paper_engine")
        if pe is not None:
            try:
                pos = pe.get_open_positions()
                if not pos: return {"has_position": False, "side": None, "qty": None, "source": "paper"}
                p = pos[0]
                return {"has_position": True, "side": p.get("direction") or p.get("side"),
                        "qty": abs(float(p.get("quantity", p.get("qty", 0)))), "source": "paper"}
            except Exception as exc:
                return {"has_position": None, "side": None, "qty": None, "source": "error", "error": str(exc)}
        return dict(exchange, source="exchange_mirrored")

    def _read_journal(self, sys: dict) -> dict:
        jrn = sys.get("journal_v2")
        if jrn is None: return {"has_position": None, "side": None, "qty": None, "source": "unavailable"}
        try:
            ot = jrn.get_open_trades()
            # Also fetch total trade count so _classify can distinguish
            # "bot never traded this session" (startup) from "position was closed"
            try:
                all_trades = jrn.get_trades(limit=1)
                total_trades = len(all_trades)
            except Exception:
                total_trades = -1  # unknown
            if not ot:
                return {"has_position": False, "side": None, "qty": None,
                        "source": "journal", "total_trades": total_trades}
            t = ot[0]
            return {"has_position": True, "side": t.get("direction"),
                    "qty": abs(float(t.get("quantity", 0))), "source": "journal",
                    "trade_id": t.get("id"), "open_count": len(ot),
                    "total_trades": total_trades}
        except Exception as exc:
            return {"has_position": None, "side": None, "qty": None, "source": "error", "error": str(exc)}

    def _classify(self, ex: dict, jv: dict, bot: dict):
        if jv.get("open_count", 0) > 1:
            return ("DUPLICATE_JOURNAL_TRADES", "critical",
                    f"Journal has {jv['open_count']} OPEN trades — must never exceed 1")
        ver = [v for v in (ex, jv, bot) if v.get("has_position") is not None]
        if len(ver) < 2: return (None, "info", "Insufficient verifiable views")
        flat = sum(1 for v in ver if v["has_position"] is False)
        open_ = sum(1 for v in ver if v["has_position"] is True)
        if flat == len(ver): return (None, "info", "All views: flat")
        if open_ == len(ver):
            sides = {v["side"] for v in ver if v.get("side")}
            if len(sides) > 1:
                return ("SIDE_MISMATCH", "critical",
                        f"Side disagreement: ex={ex.get('side')} jv={jv.get('side')}")
            qtys = {round(v["qty"], 6) for v in ver if v.get("qty") is not None}
            if len(qtys) > 1:
                return ("QUANTITY_MISMATCH", "warning",
                        f"Qty disagreement: ex={ex.get('qty')} jv={jv.get('qty')}")
            return (None, "info", "All views: open, agree")
        open_src = [v.get("source") for v in ver if v["has_position"] is True]
        flat_src = [v.get("source") for v in ver if v["has_position"] is False]
        # If the journal is flat with no recorded trades at all, this is a
        # startup-time mismatch: the exchange holds a position that was opened
        # before this bot session began and was never written to the journal.
        # Downgrade to WARNING so it doesn't fire as CRITICAL every cycle;
        # monitor_open_trades will reconcile once the position closes.
        jv_flat_no_history = (
            jv.get("has_position") is False
            and jv.get("source") == "journal"
            and jv.get("total_trades", -1) == 0
        )
        if jv_flat_no_history and "exchange" in open_src:
            return ("PRESENCE_MISMATCH", "warning",
                    f"Pre-existing exchange position not in journal (startup): open={open_src} flat={flat_src}")
        return ("PRESENCE_MISMATCH", "critical",
                f"Presence disagreement: open={open_src} flat={flat_src}")

_rce: ReconciliationEngine | None = None
_rce_lock = threading.Lock()

def get_reconciliation_engine() -> ReconciliationEngine:
    global _rce
    if _rce is None:
        with _rce_lock:
            if _rce is None:
                _rce = ReconciliationEngine()
    return _rce

def reset_reconciliation_engine() -> ReconciliationEngine:
    global _rce
    with _rce_lock:
        _rce = ReconciliationEngine()
    return _rce
