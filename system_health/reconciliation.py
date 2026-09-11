"""system_health/reconciliation.py — Position reconciliation (Exchange/Bot/Journal)

V16 §62: multi-symbol-aware reconciliation. The original single-symbol
comparison logic (_classify()) was already symbol-agnostic — it only
ever compares abstract has_position/side/qty dicts, never reads
settings.SYMBOL itself. What WAS single-symbol-hardcoded was the
data-gathering layer (_read_exchange/_read_bot/_read_journal, all
implicitly scoped to settings.SYMBOL) and the suppression/buffer state
(one set of instance attributes, meaning only one position's worth of
"have we already reported this" tracking existed at all).

run() — unchanged, byte-for-byte, for the classic single-symbol loop.
run_all_symbols() — new: runs the identical classify() logic once per
symbol discovered across exchange positions / open journal trades /
portfolio_state, with independent per-symbol suppression state, so two
different symbols mismatching at the same time are each tracked (and
suppressed once reported) on their own, not conflated into one shared
signature.
"""
from __future__ import annotations
import threading
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone
from utils.logger import get_logger
from events.event_bus import get_event_bus
logger = get_logger(__name__)

_DEFAULT_KEY = "__default__"   # run()'s internal state key -- see module docstring


@dataclass
class ReconciliationEvent:
    id: str; timestamp: str; mismatch_type: str
    exchange_view: dict; journal_view: dict; bot_view: dict
    severity: str; detail: str
    recovery_attempted: bool = False; recovery_result: str | None = None
    # V16 §62: which symbol this event is about. "" for run()'s pre-§62
    # single-symbol call sites that didn't pass one explicitly (callers
    # should treat that as settings.SYMBOL, matching this engine's own
    # prior behavior) -- run() itself always fills in settings.SYMBOL,
    # so "" only appears if a caller constructs ReconciliationEvent
    # directly, which no code in this project does.
    symbol: str = ""
    def to_dict(self) -> dict: return asdict(self)


@dataclass
class _SymbolState:
    """Per-key (per-symbol, or _DEFAULT_KEY for the classic single-
    symbol path) reconciliation state — everything run() used to keep
    as flat instance attributes, now one of these per key so multiple
    symbols' suppression/buffer state can't bleed into each other."""
    buf: list[ReconciliationEvent] = field(default_factory=list)
    last_run: str | None = None
    last_result: str | None = None
    last_fired_sig: tuple | None = None
    suppressed_repeat_count: int = 0
    last_views: dict | None = None


class ReconciliationEngine:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # V16 §62: every key's worth of state lives here now, keyed by
        # symbol (or _DEFAULT_KEY for run()'s classic single-symbol
        # path). get_recent()/status()/get_last_views() below read only
        # _DEFAULT_KEY, unchanged in observable behavior from before
        # this dict existed.
        self._states: dict[str, _SymbolState] = {_DEFAULT_KEY: _SymbolState()}

    def _state(self, key: str) -> _SymbolState:
        with self._lock:
            if key not in self._states:
                self._states[key] = _SymbolState()
            return self._states[key]

    def run(self, sys: dict) -> ReconciliationEvent | None:
        """Unchanged: single-symbol (settings.SYMBOL) reconciliation for
        the classic single-symbol loop. See run_all_symbols() for the
        SCHEDULER_ENABLED-mode equivalent."""
        from config.settings import settings
        return self._run_for_key(sys, symbol=settings.SYMBOL, key=_DEFAULT_KEY)

    def run_all_symbols(self, sys: dict) -> list[ReconciliationEvent]:
        """V16 §62: one reconciliation pass per symbol discovered across
        every open exchange position, open journal trade, and
        portfolio_state entry — the union, not the intersection, since
        a symbol appearing in only ONE of those views is exactly the
        kind of mismatch this engine exists to catch (a symbol missing
        from the union entirely, by definition, can't be a mismatch at
        all — nothing claims it has a position). Each symbol gets its
        own independent suppression state (a mismatch on XRPUSDT
        publishing/logging/recovering doesn't suppress a *different*
        mismatch on DOGEUSDT, and vice versa)."""
        symbols = self._discover_symbols(sys)
        events: list[ReconciliationEvent] = []
        for symbol in symbols:
            evt = self._run_for_key(sys, symbol=symbol, key=symbol)
            if evt is not None:
                events.append(evt)
        return events

    def _discover_symbols(self, sys: dict) -> set[str]:
        symbols: set[str] = set()
        dp = sys.get("data_provider")
        if dp is not None:
            try:
                for p in dp.get_all_positions():
                    s = p.get("symbol")
                    if s:
                        symbols.add(s)
            except Exception as exc:
                logger.debug(f"Recon symbol discovery: get_all_positions failed: {exc}")
        jrn = sys.get("journal_v2")
        if jrn is not None:
            try:
                for t in jrn.get_open_trades():
                    s = t.get("symbol")
                    if s:
                        symbols.add(s)
            except Exception as exc:
                logger.debug(f"Recon symbol discovery: get_open_trades failed: {exc}")
        ps = sys.get("portfolio_state")
        if ps is not None:
            try:
                symbols.update(ps.held_symbols())
            except Exception as exc:
                logger.debug(f"Recon symbol discovery: held_symbols failed: {exc}")
        return symbols

    def _run_for_key(self, sys: dict, symbol: str, key: str) -> ReconciliationEvent | None:
        st = self._state(key)
        try:
            ex = self._read_exchange(sys, symbol)
            bot = self._read_bot(sys, ex, symbol)
            jv = self._read_journal(sys, symbol)
            st.last_run = datetime.now(timezone.utc).isoformat()
            mt, sev, detail = self._classify(ex, jv, bot)
            st.last_views = {
                "exchange": ex, "journal": jv, "bot": bot,
                "mismatch_type": mt, "severity": sev, "detail": detail,
                "checked_at": st.last_run, "symbol": symbol,
            }
            if mt is None:
                st.last_result = "OK"
                st.last_fired_sig = None
                st.suppressed_repeat_count = 0
                return None
            st.last_result = "MISMATCH"

            sig = (mt, sev, detail)
            if sig == st.last_fired_sig:
                st.suppressed_repeat_count += 1
                return None

            evt = ReconciliationEvent(
                id=uuid.uuid4().hex[:12], timestamp=st.last_run,
                mismatch_type=mt, exchange_view=ex, journal_view=jv,
                bot_view=bot, severity=sev, detail=detail, symbol=symbol,
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
                st.buf.append(evt)
                if len(st.buf) > 200: st.buf.pop(0)
            logger.warning(f"Recon MISMATCH | {symbol} | {mt} {sev} | {detail}")
            st.last_fired_sig = sig
            st.suppressed_repeat_count = 0
            return evt
        except Exception as exc:
            logger.error(f"ReconciliationEngine.run failed ({symbol}): {exc}", exc_info=True)
            return None

    def get_recent(self, limit: int = 50) -> list[dict]:
        st = self._state(_DEFAULT_KEY)
        with self._lock: return [e.to_dict() for e in st.buf[-limit:][::-1]]

    def get_last_views(self) -> dict | None:
        """V16 Phase ORDER-01: the exchange/journal/bot views and
        classification from the most recent run() call, always fresh
        (unlike get_recent(), which only reflects *published*, non-
        suppressed mismatches). None if run() has never been called."""
        st = self._state(_DEFAULT_KEY)
        return dict(st.last_views) if st.last_views is not None else None

    def status(self) -> dict:
        st = self._state(_DEFAULT_KEY)
        return {"last_run": st.last_run, "last_result": st.last_result,
                "event_count": len(st.buf),
                "suppressed_repeat_count": st.suppressed_repeat_count}

    # ── V16 §62: multi-symbol accessors — additive, mirror the single-
    # symbol ones above but keyed/aggregated across every symbol
    # run_all_symbols() has ever seen. ──────────────────────────────────

    def get_recent_for_symbol(self, symbol: str, limit: int = 50) -> list[dict]:
        st = self._state(symbol)
        with self._lock: return [e.to_dict() for e in st.buf[-limit:][::-1]]

    def get_last_views_for_symbol(self, symbol: str) -> dict | None:
        st = self._state(symbol)
        return dict(st.last_views) if st.last_views is not None else None

    def status_all_symbols(self) -> dict[str, dict]:
        """One status() dict per symbol currently tracked (excludes
        _DEFAULT_KEY — that one's run()'s own, surfaced via status())."""
        with self._lock:
            keys = [k for k in self._states if k != _DEFAULT_KEY]
        return {
            k: {"last_run": s.last_run, "last_result": s.last_result,
                "event_count": len(s.buf),
                "suppressed_repeat_count": s.suppressed_repeat_count}
            for k, s in ((k, self._state(k)) for k in keys)
        }

    def _read_exchange(self, sys: dict, symbol: str | None = None) -> dict:
        dp = sys.get("data_provider")
        if dp is None: return {"has_position": None, "side": None, "qty": None, "source": "unavailable"}
        try:
            pos = dp.get_position_info(symbol=symbol)
            if pos is None: return {"has_position": False, "side": None, "qty": None, "source": "exchange"}
            return {"has_position": True, "side": pos.get("side"),
                    "qty": abs(float(pos.get("positionAmt", 0))), "source": "exchange"}
        except Exception as exc:
            return {"has_position": None, "side": None, "qty": None, "source": "error", "error": str(exc)}

    def _read_bot(self, sys: dict, exchange: dict, symbol: str | None = None) -> dict:
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
        # V16 Phase ORDER-01 (BUG-LIVE-ORDER-01 root cause): live mode
        # previously returned `dict(exchange, source="exchange_mirrored")`
        # here — a literal copy of the exchange view, not an independent
        # read. That made "bot" and "exchange" definitionally identical in
        # live mode, so this engine could never detect a stale runtime
        # position cache (portfolio/portfolio_state.py's PortfolioState,
        # whose own docstring already admits nothing keeps it in sync with
        # reality). Reading it independently here is what makes that ghost
        # visible to `_classify()` at all. Falls back to the old mirrored
        # behavior when no PortfolioState is wired in.
        ps = sys.get("portfolio_state")
        if ps is not None:
            try:
                from config.settings import settings
                target_symbol = symbol or settings.SYMBOL
                pos = ps.get_position(target_symbol)
                if pos is None:
                    return {"has_position": False, "side": None, "qty": None, "source": "portfolio_state"}
                return {"has_position": True, "side": pos.direction,
                        "qty": abs(float(pos.quantity)), "source": "portfolio_state"}
            except Exception as exc:
                return {"has_position": None, "side": None, "qty": None, "source": "error", "error": str(exc)}
        return dict(exchange, source="exchange_mirrored")

    def _read_journal(self, sys: dict, symbol: str | None = None) -> dict:
        jrn = sys.get("journal_v2")
        if jrn is None: return {"has_position": None, "side": None, "qty": None, "source": "unavailable"}
        try:
            from config.settings import settings
            target_symbol = symbol or settings.SYMBOL
            ot_all = jrn.get_open_trades()
            # V16 §62: scoped to target_symbol so run_all_symbols() sees
            # "duplicate open trades for THIS symbol", not "the journal
            # has more than one open trade anywhere" — the latter is
            # completely normal and expected once more than one symbol
            # can legitimately have an open position at once.
            ot = [t for t in ot_all if (t.get("symbol") or settings.SYMBOL) == target_symbol]
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
