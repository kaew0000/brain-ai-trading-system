"""
tools/close_orphaned_position.py — one-off operational script

Purpose
-------
Flattens a real exchange position that RecoveryEngine's BUG-LIVE-RISK-02
orphan-protection path has already detected (a real Binance position with
no journal record — see system_health/recovery_engine.py). Reuses the
existing, already-tested TradeManager.close_position() (reduceOnly
market close with retries + duplicate-order recovery) instead of
duplicating any order-placement logic here.

This does NOT touch RecoveryEngine's in-memory orphan hold — that hold
lives only inside the running bot process and clears itself the next
time that process starts fresh (a new RecoveryEngine has no hold) and
reconciliation finds the exchange flat. If you'd rather not restart the
bot, acknowledge the hold instead via
POST /api/system/reconciliation/acknowledge (or
RecoveryEngine.acknowledge_orphaned_position()) — this script does not
call that for you, by design: closing the position and acknowledging
the hold are two separate, independently-auditable actions.

Safety
------
Hard-refuses to run unless settings.BINANCE_TESTNET is True. There is no
flag to override this — if you genuinely need to flatten a MAINNET
position, do it directly through Binance (UI or your own tooling) with
full manual control, not through an unattended script. This tool exists
for the specific, low-stakes testnet case.

Usage
-----
    python -m tools.close_orphaned_position          # dry run — shows the
                                                       # position, asks for
                                                       # typed confirmation
    python -m tools.close_orphaned_position --yes     # skip the prompt
                                                       # (for scripted use)
"""
from __future__ import annotations

import argparse
import sys

from utils.logger import get_logger

logger = get_logger(__name__)


def close_orphaned_position(dp, tm, auto_confirm: bool = False) -> int:
    """
    Core logic, independent of CLI wiring, for testability.

    Parameters
    ----------
    dp : BinanceDataProvider (or any object exposing get_position_info())
    tm : TradeManager (or any object exposing close_position())
    auto_confirm : skip the typed-YES prompt (still refuses on no position)

    Returns
    -------
    0  success (position closed, or nothing to close)
    1  refused / cancelled by operator
    2  close_position() call failed or left a non-zero position
    """
    pos = dp.get_position_info()
    if pos is None:
        logger.info("close_orphaned_position: no open position — nothing to do.")
        return 0

    symbol      = pos.get("symbol")
    direction   = pos.get("side")
    qty         = pos.get("positionAmt")
    entry_price = pos.get("entryPrice")

    print(f"Open position found: {direction} {qty} {symbol} @ entry {entry_price}")
    print("This will place a REDUCE-ONLY MARKET order to flatten it.")

    if not auto_confirm:
        typed = input("Type YES to close this position: ").strip()
        if typed != "YES":
            print("Cancelled — no order placed.")
            return 1

    order = tm.close_position(direction, qty)
    if order is None:
        logger.error("close_orphaned_position: close_position() returned None — order was not confirmed.")
        return 2

    logger.info(f"close_orphaned_position: close order confirmed: {order}")

    # Re-query to confirm the exchange is actually flat now — don't just
    # trust the order response, the same "verify against exchange truth"
    # principle RecoveryEngine itself follows.
    after = dp.get_position_info()
    if after is not None:
        logger.error(
            f"close_orphaned_position: exchange still reports a position "
            f"after close: {after} — do not assume this is resolved."
        )
        return 2

    print("Position confirmed flat on the exchange.")
    print(
        "Note: the running bot process's in-memory orphan hold (if any) is "
        "NOT cleared by this script. Restart the bot for a fresh "
        "RecoveryEngine, or call acknowledge_orphaned_position() / "
        "POST /api/system/reconciliation/acknowledge if you'd rather not "
        "restart."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--yes", action="store_true", help="Skip the typed confirmation prompt")
    args = parser.parse_args()

    from config.settings import settings
    if not settings.BINANCE_TESTNET:
        logger.error(
            "close_orphaned_position: refusing to run — BINANCE_TESTNET is "
            "False (mainnet). This script only operates on testnet. Close "
            "a real mainnet position directly through Binance."
        )
        return 1

    from data.binance_provider import BinanceDataProvider
    from execution.trade_manager import TradeManager

    dp = BinanceDataProvider()
    tm = TradeManager(dp)
    return close_orphaned_position(dp, tm, auto_confirm=args.yes)


if __name__ == "__main__":
    sys.exit(main())
