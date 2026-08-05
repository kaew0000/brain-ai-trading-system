"""C1 Exchange State Manager.

ExchangeStateManager is the single source of truth for "what does the
exchange say our account/positions/orders look like right now" — for
read-only consumers (World/C2 Position Lifecycle, C3 Dashboard, C4
CEO/AI Context). It is NOT a trading component: it never places, cancels,
or modifies an order, and nothing in the trading engine's decision path
is required to go through it.

Architecture (per repo owner's C1 v2 review):

    caller (World / Dashboard / CEO context)
            |
            v
    ExchangeStateManager   <-- this file. Orchestration ONLY: refresh,
            |                   cache (single ExchangeSnapshot), mode
            |                   isolation, thread safety, stale/degraded
            |                   fallback. No Binance JSON parsing here.
            v
    BinanceDataProvider    <-- existing V15/V16 component. This is the
            |                   ONLY thing that talks to UMFutures and the
            |                   ONLY thing that parses raw Binance JSON.
            |                   get_account_snapshot()/get_open_orders()/
            |                   get_server_time() are additive methods on
            |                   it (see data/binance_provider.py) that
            |                   already do this parsing.
            v
    UMFutures client (existing retry/circuit-breaker wrapped calls)

One refresh() = exactly 2 upstream calls (account snapshot + open
orders), not one call per field. Funding rate is intentionally excluded
— it is market data, not exchange/account state.
"""
from __future__ import annotations

import threading
import time
import uuid

from utils.logger import get_logger
from exchange_state.constants import (
    VALID_MODES,
    DEFAULT_SNAPSHOT_TTL_SECONDS,
    DEFAULT_EXCHANGE,
    DEFAULT_ACCOUNT_ID,
)
from exchange_state.models import (
    AccountSnapshot,
    PositionSnapshot,
    OrderSnapshot,
    ExchangeSnapshot,
)

logger = get_logger(__name__)

_EMPTY_ACCOUNT = AccountSnapshot(
    wallet_balance=0.0, available_balance=0.0, unrealized_pnl=0.0,
    total_margin_balance=0.0, maintenance_margin=0.0, initial_margin=0.0,
)


def _classify_stale_reason(exc: Exception) -> str:
    """Best-effort string classification for the UI/logs. This is a
    simple heuristic over the exception's own message/type, not an
    exhaustive Binance-error-code mapping — documented here so nobody
    mistakes it for one."""
    msg = str(exc).lower()
    if "timeout" in msg or "timed out" in msg:
        return "timeout"
    if "rate limit" in msg or "-1003" in msg or "too many requests" in msg:
        return "rate_limit"
    if "maintenance" in msg or "-1001" in msg:
        return "maintenance"
    return "network"


class ExchangeStateManager:
    def __init__(
        self,
        data_provider,
        mode: str,
        exchange: str = DEFAULT_EXCHANGE,
        account_id: str = DEFAULT_ACCOUNT_ID,
        ttl_seconds: float = DEFAULT_SNAPSHOT_TTL_SECONDS,
    ) -> None:
        if mode not in VALID_MODES:
            raise ValueError(f"Invalid mode={mode!r}; must be one of {VALID_MODES}")
        self._dp = data_provider
        self.mode = mode
        self.exchange = exchange
        self.account_id = account_id
        self.ttl_seconds = ttl_seconds

        self._lock = threading.RLock()
        self._snapshot: ExchangeSnapshot | None = None
        self._revision = 0
        self._consecutive_failures = 0
        # (side, quantity, entry_price) per symbol as of the last snapshot,
        # used only to detect a real position change and bump `version`.
        self._position_state: dict[str, tuple] = {}
        self._position_version: dict[str, int] = {}

    # ── Public read API ──────────────────────────────────────────────

    def get_snapshot(self, force: bool = False) -> ExchangeSnapshot:
        with self._lock:
            if not force and self._snapshot is not None and not self._is_stale_locked():
                return self._snapshot
        reason = "manual" if force else ("scheduled" if self._snapshot else "startup")
        return self.refresh(reason=reason)

    def get_account(self) -> AccountSnapshot:
        return self.get_snapshot().account

    def get_positions(self) -> list[PositionSnapshot]:
        return list(self.get_snapshot().positions.values())

    def get_position(self, symbol: str) -> PositionSnapshot | None:
        return self.get_snapshot().positions.get(symbol)

    def get_orders(self) -> tuple[OrderSnapshot, ...]:
        return self.get_snapshot().orders

    def is_stale(self) -> bool:
        with self._lock:
            return self._is_stale_locked()

    def status(self) -> dict:
        with self._lock:
            snap = self._snapshot
            return {
                "mode": self.mode,
                "exchange": self.exchange,
                "account_id": self.account_id,
                "revision": self._revision,
                "has_snapshot": snap is not None,
                "is_stale": self._is_stale_locked(),
                "degraded": snap.degraded if snap else None,
                "health_score": snap.health_score if snap else None,
                "consecutive_failures": self._consecutive_failures,
            }

    # ── Refresh (the only place that talks to the provider) ────────────

    def refresh(self, reason: str = "manual") -> ExchangeSnapshot:
        with self._lock:
            try:
                account_raw = self._dp.get_account_snapshot()
                orders_raw = self._dp.get_open_orders()
            except Exception as exc:
                return self._handle_refresh_failure(exc, reason)

            account = AccountSnapshot(
                wallet_balance=account_raw["wallet_balance"],
                available_balance=account_raw["available_balance"],
                unrealized_pnl=account_raw["unrealized_pnl"],
                total_margin_balance=account_raw["total_margin_balance"],
                maintenance_margin=account_raw["maintenance_margin"],
                initial_margin=account_raw["initial_margin"],
            )

            positions: dict[str, PositionSnapshot] = {}
            for p in account_raw.get("positions", []):
                symbol = p["symbol"]
                state = (p["side"], p["quantity"], p["entry_price"])
                if self._position_state.get(symbol) != state:
                    self._position_version[symbol] = self._position_version.get(symbol, 0) + 1
                self._position_state[symbol] = state
                positions[symbol] = PositionSnapshot(
                    symbol=symbol,
                    side=p["side"],
                    quantity=p["quantity"],
                    entry_price=p["entry_price"],
                    mark_price=p["mark_price"],
                    unrealized_pnl=p["unrealized_pnl"],
                    leverage=p["leverage"],
                    margin_type=p["margin_type"],
                    liquidation_price=p["liquidation_price"],
                    version=self._position_version[symbol],
                )
            # symbols that closed since the last snapshot drop out of
            # `positions` naturally (account_raw simply won't list them);
            # clear their tracked state so a future re-open starts fresh.
            for gone in set(self._position_state) - set(positions):
                self._position_state.pop(gone, None)
                self._position_version.pop(gone, None)

            orders = tuple(
                OrderSnapshot(
                    symbol=o["symbol"],
                    order_id=o["order_id"],
                    client_order_id=o["client_order_id"],
                    side=o["side"],
                    type=o["type"],
                    status=o["status"],
                    stop_price=o["stop_price"],
                    orig_qty=o["orig_qty"],
                    executed_qty=o["executed_qty"],
                    reduce_only=o["reduce_only"],
                )
                for o in orders_raw
            )

            self._revision += 1
            self._consecutive_failures = 0
            self._snapshot = ExchangeSnapshot(
                mode=self.mode, exchange=self.exchange, account_id=self.account_id,
                account=account, positions=positions, orders=orders,
                revision=self._revision, snapshot_uuid=uuid.uuid4().hex,
                fetched_at=time.time(), sync_reason=reason,
                last_sync_source="rest", degraded=False, stale_reason=None,
                health_score=100,
            )
            return self._snapshot

    # ── Internal ─────────────────────────────────────────────────────

    def _is_stale_locked(self) -> bool:
        if self._snapshot is None:
            return True
        return (time.time() - self._snapshot.fetched_at) > self.ttl_seconds

    def _handle_refresh_failure(self, exc: Exception, reason: str) -> ExchangeSnapshot:
        self._consecutive_failures += 1
        stale_reason = _classify_stale_reason(exc)
        logger.warning(
            f"ExchangeStateManager[{self.mode}] refresh failed "
            f"(attempt #{self._consecutive_failures}, reason={stale_reason}): {exc}"
        )
        if self._snapshot is not None:
            # Return stale data rather than raising — a dashboard/World
            # consumer showing 3-second-old numbers is far better than one
            # that crashes or blanks out on a single transient error.
            health = max(20, 100 - 20 * self._consecutive_failures)
            self._snapshot = ExchangeSnapshot(
                mode=self._snapshot.mode, exchange=self._snapshot.exchange,
                account_id=self._snapshot.account_id, account=self._snapshot.account,
                positions=self._snapshot.positions, orders=self._snapshot.orders,
                revision=self._snapshot.revision, snapshot_uuid=self._snapshot.snapshot_uuid,
                fetched_at=self._snapshot.fetched_at, sync_reason=reason,
                last_sync_source=self._snapshot.last_sync_source,
                degraded=True, stale_reason=stale_reason, health_score=health,
            )
            return self._snapshot
        # No prior snapshot at all (e.g. failed on startup) — hand back an
        # explicitly empty, explicitly degraded snapshot rather than None,
        # so callers never need a null check.
        self._revision += 1
        self._snapshot = ExchangeSnapshot(
            mode=self.mode, exchange=self.exchange, account_id=self.account_id,
            account=_EMPTY_ACCOUNT, positions={}, orders=(),
            revision=self._revision, snapshot_uuid=uuid.uuid4().hex,
            fetched_at=time.time(), sync_reason=reason, last_sync_source="rest",
            degraded=True, stale_reason=stale_reason, health_score=0,
        )
        return self._snapshot


# ── Singleton registry: one manager per (mode, exchange, account_id) ────

_registry: dict[tuple, ExchangeStateManager] = {}
_registry_lock = threading.Lock()


def get_manager(
    data_provider,
    mode: str,
    exchange: str = DEFAULT_EXCHANGE,
    account_id: str = DEFAULT_ACCOUNT_ID,
    ttl_seconds: float = DEFAULT_SNAPSHOT_TTL_SECONDS,
) -> ExchangeStateManager:
    key = (mode, exchange, account_id)
    with _registry_lock:
        mgr = _registry.get(key)
        if mgr is None:
            mgr = ExchangeStateManager(data_provider, mode, exchange, account_id, ttl_seconds)
            _registry[key] = mgr
        return mgr


def reset_registry() -> None:
    """Test-only: clear the singleton registry between test cases."""
    with _registry_lock:
        _registry.clear()
