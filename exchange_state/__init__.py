"""C1 — Exchange State Manager.

Read-only, single-source-of-truth snapshots of exchange account/position/
order state for World/C2/C3/C4 consumers. See
docs/architecture/EXCHANGE_STATE_MANAGER.md for the design.
"""
from exchange_state.manager import ExchangeStateManager, get_manager, reset_registry
from exchange_state.models import (
    AccountSnapshot,
    PositionSnapshot,
    OrderSnapshot,
    ExchangeSnapshot,
)

__all__ = [
    "ExchangeStateManager",
    "get_manager",
    "reset_registry",
    "AccountSnapshot",
    "PositionSnapshot",
    "OrderSnapshot",
    "ExchangeSnapshot",
]
