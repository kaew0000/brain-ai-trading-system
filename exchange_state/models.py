"""C1 Exchange State Manager — immutable snapshot models.

Design constraints (per repo owner's C1 v2 review — see
docs/architecture/EXCHANGE_STATE_MANAGER.md):
  - No business logic here. Pure data.
  - Every instance is frozen — once built, it never mutates. Safe to hand
    the same object to multiple threads/readers (World, Dashboard, CEO)
    without copying.
  - Funding rate is deliberately NOT modeled here — it's market data, not
    exchange/account state, and belongs in the market-context/feature
    layer, not C1.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class PositionSnapshot:
    """One open position, as already parsed by BinanceDataProvider —
    ExchangeStateManager never re-parses raw Binance JSON itself."""
    symbol: str
    side: str                # "LONG" | "SHORT"
    quantity: float
    entry_price: float
    mark_price: float
    unrealized_pnl: float
    leverage: int
    margin_type: str
    liquidation_price: float
    version: int = 1          # incremented by the manager whenever this
                               # symbol's (side, quantity, entry_price)
                               # changes between refreshes


@dataclass(frozen=True, slots=True)
class OrderSnapshot:
    """One open order."""
    symbol: str
    order_id: int
    client_order_id: str
    side: str
    type: str
    status: str
    stop_price: float
    orig_qty: float
    executed_qty: float
    reduce_only: bool

    @property
    def is_sl(self) -> bool:
        return self.type in ("STOP_MARKET", "STOP") and self.reduce_only

    @property
    def is_tp(self) -> bool:
        return self.type in ("TAKE_PROFIT_MARKET", "TAKE_PROFIT") and self.reduce_only


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    """Account-level balances/margin. Does not include positions or
    orders — those live as their own fields on ExchangeSnapshot so each
    can be read/compared independently."""
    wallet_balance: float
    available_balance: float
    unrealized_pnl: float
    total_margin_balance: float
    maintenance_margin: float
    initial_margin: float


@dataclass(frozen=True, slots=True)
class ExchangeSnapshot:
    """The single unit of state C1 hands out. One ExchangeSnapshot per
    (mode, exchange, account_id) — this IS "the cache"; there is no
    separate account/position/order/margin cache to keep in sync with
    each other, by design (v2 review point #3).
    """
    mode: str                 # "paper" | "testnet" | "live"
    exchange: str              # "binance"
    account_id: str
    account: AccountSnapshot
    positions: dict[str, PositionSnapshot] = field(default_factory=dict)
    orders: tuple[OrderSnapshot, ...] = field(default_factory=tuple)

    revision: int = 0          # increments every successful refresh
    snapshot_uuid: str = ""    # unique id for this exact snapshot, for tracing
    fetched_at: float = 0.0    # time.time() when this snapshot was built

    sync_reason: str = "startup"     # startup | manual | scheduled | reconnect | order_fill
    last_sync_source: str = "rest"   # rest | websocket | recovery | reconnect
    degraded: bool = False
    stale_reason: str | None = None  # timeout | rate_limit | network | maintenance | None
    health_score: int = 100          # 0-100, simple heuristic — see manager.py

    @property
    def open_position_count(self) -> int:
        return len(self.positions)

    def get_position(self, symbol: str) -> PositionSnapshot | None:
        return self.positions.get(symbol)
