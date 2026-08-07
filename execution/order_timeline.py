"""
execution/order_timeline.py — Track C3 Phase 1: Unified Order/Trade
Timeline (read-model)

Merges two existing, UNMODIFIED sources of truth into one read-only
view for the dashboard. Introduces no new authority:

  - execution/trade_lifecycle.py's TradeLifecycle remains the sole
    authority for TRADE-level lifecycle (PENDING/EXECUTING/OPEN/
    MONITORING/EXIT_REQUESTED/EXIT_EXECUTING/CLOSED/FAILED).
  - exchange_state/manager.py's ExchangeStateManager (C1) remains the
    sole authority for raw EXCHANGE ORDER state (Binance order
    `status` strings — NEW/PARTIALLY_FILLED/FILLED/CANCELED/... — on
    OrderSnapshot).

OrderTimeline only calls each source's existing public read methods
(TradeLifecycle.get_handle_snapshot()/snapshot(), ExchangeStateManager.
get_orders()) and derives a composite display state from the two. It
never calls open_pending()/request_exit()/etc., never calls refresh()
on the exchange manager (that cadence belongs to whoever already owns
it — C1 is a pull-based cache; this module reads whatever snapshot is
already current), and never writes back to either source. Nothing in
the trading engine's decision path depends on this module — same
additive posture C1's own docs/architecture/EXCHANGE_STATE_MANAGER.md
documents for itself.

Known limitation, documented rather than silently assumed away:
TradeLifecycle has no partial-position-reduce concept today — a
position is opened once and closed once per symbol (see trade_lifecycle
.py's own _TRANSITIONS table). The composite REDUCING state below is
defined for forward-compatibility with the dashboard's requested
vocabulary, but nothing in this codebase can currently produce it —
compose_state() will never return it — until TradeLifecycle itself
gains a partial-close concept. FILLED-via-raw-order-status is similarly
a narrow window: Binance's open-orders endpoint (what C1's
get_orders() reflects) drops an order once it's fully filled, so the
FILLED composite state is primarily reached via TradeLifecycle's own
OPEN state (see open_confirmed()'s docstring: "Entry order filled" is
exactly what that transition means), not via a lingering OrderSnapshot.

Threading model mirrors scanner/market_scanner.py / execution/
execution_scheduler.py exactly — daemon thread + threading.Event, same
start()/stop()/is_running()/run_once() shape, so run_once() can be
driven synchronously by tests (or any future caller) without touching
threading at all.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

from database.db import ManagedConn, ReadConn
from events.event_bus import get_event_bus
from execution.trade_lifecycle import TradeLifecycle, TradeLifecycleState
from utils.logger import get_logger

logger = get_logger("execution.order_timeline")

# Ring buffer size for the in-memory recent() view — mirrors
# execution/execution_state.py's _HISTORY_SIZE (500) and events/
# event_bus.py's _RING_BUFFER_SIZE (1000) choices; this module sits
# between those two in expected volume (one entry per observed STATE
# CHANGE, not per poll tick and not per raw event).
_RING_BUFFER_SIZE = 500

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS order_timeline_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp    TEXT    NOT NULL,
    symbol       TEXT    NOT NULL,
    trade_id     INTEGER,
    order_id     TEXT,
    state_before TEXT,
    state_after  TEXT    NOT NULL,
    source       TEXT    NOT NULL,
    reason       TEXT
);
CREATE INDEX IF NOT EXISTS idx_order_timeline_symbol
    ON order_timeline_history(symbol, id);
"""


# ── Composite display states ─────────────────────────────────────────
#
# This is this phase's OWN vocabulary — a derived/display view, not a
# fourth state machine. Nothing external transitions these directly;
# compose_state() below is a pure function of the two real sources.
class TimelineState:
    NEW              = "NEW"
    SUBMITTED        = "SUBMITTED"
    ACKNOWLEDGED     = "ACKNOWLEDGED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED           = "FILLED"
    OPEN             = "OPEN"
    REDUCING         = "REDUCING"   # see module docstring — not yet producible
    CLOSING          = "CLOSING"
    CLOSED           = "CLOSED"
    FAILED           = "FAILED"
    CANCELLED        = "CANCELLED"


_TRADE_STATE_TO_TIMELINE = {
    TradeLifecycleState.PENDING:        TimelineState.NEW,
    TradeLifecycleState.EXECUTING:      TimelineState.SUBMITTED,
    TradeLifecycleState.OPEN:           TimelineState.FILLED,
    TradeLifecycleState.MONITORING:     TimelineState.OPEN,
    TradeLifecycleState.EXIT_REQUESTED: TimelineState.CLOSING,
    TradeLifecycleState.EXIT_EXECUTING: TimelineState.CLOSING,
    TradeLifecycleState.CLOSED:         TimelineState.CLOSED,
    TradeLifecycleState.FAILED:         TimelineState.FAILED,
}

_ORDER_STATUS_REFINEMENT = {
    "NEW":             TimelineState.ACKNOWLEDGED,
    "PARTIALLY_FILLED": TimelineState.PARTIALLY_FILLED,
    "FILLED":          TimelineState.FILLED,
    "CANCELED":        TimelineState.CANCELLED,
    "EXPIRED":         TimelineState.CANCELLED,
    "REJECTED":        TimelineState.CANCELLED,
}


def compose_state(trade_state: TradeLifecycleState | None, order_status: str | None) -> str:
    """Pure function: (TradeLifecycle state, latest known raw exchange
    order status for that symbol) -> one composite display state.

    Order-level granularity (ACKNOWLEDGED/PARTIALLY_FILLED/CANCELLED)
    only refines the EXECUTING window, since that's the only
    TradeLifecycle phase where an entry order can genuinely be
    in-flight-but-not-yet-resolved; every other TradeLifecycle state
    already implies a specific composite state regardless of the raw
    order status (see _TRADE_STATE_TO_TIMELINE above)."""
    if trade_state is None:
        return TimelineState.NEW
    if trade_state == TradeLifecycleState.EXECUTING and order_status in _ORDER_STATUS_REFINEMENT:
        return _ORDER_STATUS_REFINEMENT[order_status]
    return _TRADE_STATE_TO_TIMELINE.get(trade_state, TimelineState.NEW)


@dataclass
class TimelineEntry:
    timestamp:    str
    symbol:       str
    state_before: str | None
    state_after:  str
    source:       str
    reason:       str | None = None
    trade_id:     int | None = None
    order_id:     str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


class OrderTimeline:
    """Read-only merge of TradeLifecycle + ExchangeStateManager. Owns no
    trade/order authority itself — see module docstring."""

    # Trim check runs every N persisted BATCHES (not every insert) — a
    # cheap in-process counter, not a COUNT(*) on every write.
    _TRIM_CHECK_INTERVAL = 200

    def __init__(
        self,
        trade_lifecycle: TradeLifecycle,
        exchange_manager=None,
        db_path: str | None = None,
        poll_interval_seconds: float = 5.0,
        max_history_rows: int = 100_000,
    ) -> None:
        self._lifecycle = trade_lifecycle
        # Optional: dashboard-only / backtest deployments without live
        # exchange credentials still get correct TRADE-level composite
        # states (NEW/SUBMITTED/OPEN/CLOSING/CLOSED/FAILED) — they just
        # never see the ACKNOWLEDGED/PARTIALLY_FILLED/CANCELLED
        # refinements, which need C1. Never constructed here — callers
        # already hold (or don't hold) a real ExchangeStateManager; this
        # module does not invent a BinanceDataProvider to build one.
        self._exchange = exchange_manager
        self._db_path = db_path
        self._poll_interval = poll_interval_seconds
        self._max_history_rows = max_history_rows
        self._persist_count = 0

        self._lock = threading.Lock()
        self._buffer: list[TimelineEntry] = []
        # symbol -> last composed TimelineState. Bounded by the traded
        # symbol universe (tens, not thousands) — not by trade count —
        # so this dict does not grow unboundedly over a long-running
        # process (rule: avoid memory leaks).
        self._last_state: dict[str, str] = {}

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        self._ensure_schema()

    # ── schema ──────────────────────────────────────────────────────
    def _ensure_schema(self) -> None:
        try:
            with ManagedConn(self._db_path) as conn:
                conn.executescript(_SCHEMA_SQL)
                conn.commit()
        except Exception as exc:
            logger.error(f"OrderTimeline: schema init failed (non-fatal): {exc}")

    # ── one merge cycle ───────────────────────────────────────────────
    def run_once(self) -> list[TimelineEntry]:
        """One merge cycle: read both sources, diff against last-seen
        composite state per symbol, persist + publish only the symbols
        that actually changed. Safe to call directly (tests, manual
        trigger, or a future caller on its own cadence) without
        start()'ing the background thread at all."""
        live_symbols = set(self._lifecycle.known_symbols())
        tracked_symbols = live_symbols | set(self._last_state)

        order_status_by_symbol: dict[str, str] = {}
        if self._exchange is not None:
            try:
                for o in self._exchange.get_orders():
                    order_status_by_symbol[o.symbol] = o.status
            except Exception as exc:
                logger.warning(f"OrderTimeline: ExchangeStateManager read failed (non-fatal): {exc}")

        new_entries: list[TimelineEntry] = []
        for symbol in tracked_symbols:
            info = self._lifecycle.get_handle_snapshot(symbol)
            trade_state = TradeLifecycleState(info["state"]) if info else None
            composed = compose_state(trade_state, order_status_by_symbol.get(symbol))
            previous = self._last_state.get(symbol)

            if composed == previous:
                continue

            new_entries.append(TimelineEntry(
                timestamp=datetime.now(timezone.utc).isoformat(),
                symbol=symbol,
                state_before=previous,
                state_after=composed,
                source="ORDER_TIMELINE",
                reason=info.get("exit_reason") if info else None,
                trade_id=info.get("trade_id") if info else None,
                order_id=None,
            ))
            self._last_state[symbol] = composed

        if new_entries:
            with self._lock:
                self._buffer.extend(new_entries)
                overflow = len(self._buffer) - _RING_BUFFER_SIZE
                if overflow > 0:
                    del self._buffer[:overflow]
            self._persist(new_entries)
            self._publish_events(new_entries)

        return new_entries

    def _persist(self, entries: list[TimelineEntry]) -> None:
        try:
            with ManagedConn(self._db_path) as conn:
                conn.executemany(
                    """INSERT INTO order_timeline_history
                       (timestamp, symbol, trade_id, order_id, state_before, state_after, source, reason)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    [
                        (e.timestamp, e.symbol, e.trade_id, e.order_id,
                         e.state_before, e.state_after, e.source, e.reason)
                        for e in entries
                    ],
                )
                conn.commit()
        except Exception as exc:
            # Non-fatal: the in-memory buffer above already has these
            # entries, so current_state()/recent() stay correct even if
            # a write blip drops this cycle from persisted history().
            logger.error(f"OrderTimeline: persist failed (non-fatal): {exc}")
            return

        self._persist_count += 1
        if self._persist_count % self._TRIM_CHECK_INTERVAL == 0:
            self._trim_history()

    def _trim_history(self) -> None:
        """Row-count cap (config: ORDER_TIMELINE_HISTORY_MAX_ROWS) so
        order_timeline_history cannot grow unbounded on a long-running
        process. This is operational history only — see module
        docstring — trimming the oldest rows loses no journal data.
        Uses MAX(id) (indexed, O(1)) rather than COUNT(*) to find the
        cutoff, so this stays cheap even on a large table."""
        try:
            with ManagedConn(self._db_path) as conn:
                conn.execute(
                    """DELETE FROM order_timeline_history
                       WHERE id <= (SELECT MAX(id) FROM order_timeline_history) - ?""",
                    (self._max_history_rows,),
                )
                conn.commit()
        except Exception as exc:
            logger.error(f"OrderTimeline: history trim failed (non-fatal): {exc}")

    def _publish_events(self, entries: list[TimelineEntry]) -> None:
        bus = get_event_bus()
        for e in entries:
            try:
                bus.publish(
                    agent="order_timeline",
                    event="STATE_TRANSITION",
                    message=f"{e.symbol}: {e.state_before} -> {e.state_after}",
                    severity="info",
                    payload=e.to_dict(),
                )
            except Exception as exc:
                logger.warning(f"OrderTimeline: event publish failed (non-fatal): {exc}")

    # ── reads ───────────────────────────────────────────────────────
    def current_state(self, symbol: str | None = None):
        with self._lock:
            if symbol is not None:
                return {"symbol": symbol, "state": self._last_state.get(symbol)}
            return [{"symbol": s, "state": st} for s, st in self._last_state.items()]

    def recent(self, symbol: str | None = None, limit: int = 50) -> list[dict]:
        """In-memory ring buffer — fast, but lost on restart. Use
        history() for the persisted view."""
        with self._lock:
            items = list(self._buffer)
        items.reverse()
        if symbol:
            items = [e for e in items if e.symbol == symbol]
        return [e.to_dict() for e in items[:limit]]

    def history(self, symbol: str | None = None, limit: int = 100) -> list[dict]:
        """Persisted history — survives restart, unlike recent()'s
        in-memory ring buffer. This is operational history only, kept
        in its own table — it does not read or duplicate the journal."""
        query = "SELECT * FROM order_timeline_history"
        params: list = []
        if symbol:
            query += " WHERE symbol = ?"
            params.append(symbol)
        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)
        try:
            with ReadConn(self._db_path) as conn:
                rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]
        except Exception as exc:
            logger.error(f"OrderTimeline: history read failed: {exc}")
            return []

    # ── background thread (mirrors scanner/market_scanner.py /
    #    execution/execution_scheduler.py exactly) ────────────────────
    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True, name="OrderTimeline")
        self._thread.start()
        logger.info(f"OrderTimeline: started (poll_interval={self._poll_interval}s)")

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        logger.info("OrderTimeline: stopped")

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                self.run_once()
            except Exception as exc:
                logger.error(f"OrderTimeline: cycle failed (non-fatal): {exc}")
            self._stop_event.wait(self._poll_interval)


# ── Process-wide default instance ───────────────────────────────────────
#
# Mirrors execution/execution_state.py's get_execution_state() / execution
# /trade_lifecycle.py's get_default_trade_lifecycle() double-checked-
# locking pattern exactly, including the same "constructor args only
# matter on the very first call" behavior those two already document —
# most callers (main.py's bootstrap, api/lifecycle_api.py's dashboard
# read layer) want ONE well-known OrderTimeline they can all reach.
_instance: OrderTimeline | None = None
_instance_lock = threading.Lock()


def get_order_timeline(
    trade_lifecycle: TradeLifecycle | None = None,
    exchange_manager=None,
    db_path: str | None = None,
    poll_interval_seconds: float = 5.0,
    max_history_rows: int = 100_000,
) -> OrderTimeline:
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                from execution.trade_lifecycle import get_default_trade_lifecycle
                _instance = OrderTimeline(
                    trade_lifecycle=trade_lifecycle or get_default_trade_lifecycle(),
                    exchange_manager=exchange_manager,
                    db_path=db_path,
                    poll_interval_seconds=poll_interval_seconds,
                    max_history_rows=max_history_rows,
                )
    return _instance


def reset_order_timeline() -> None:
    """Test-only: force a fresh singleton on the next get_order_timeline()
    call. Mirrors reset_default_trade_lifecycle()/reset_execution_state()."""
    global _instance
    with _instance_lock:
        _instance = None
