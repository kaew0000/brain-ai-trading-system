#!/usr/bin/env python3
"""
Brain Bot -- Live Account Balance Diagnostic
=============================================
fix/live-balance-zero-diagnostics

One-off operator script. Run manually (never inside the trading loop)
to answer: "why does get_account_balance() return 0.0?"

    python scripts/diagnose_balance.py

Constructs the exact same BinanceDataProvider the live bot builds in
main.py's build_system() (data/binance_provider.py -- __init__ reads
everything it needs from config/settings.py, which already
auto-loads .env at import time, so no extra wiring is duplicated
here), then calls trade_client.balance() directly and prints the FULL
raw response plus which environment/account it is pointed at.

This is a local diagnostic run by the operator on demand -- full
response detail is intentionally printed to stdout only. It never
writes to logs/brain_bot.log, so it is safe to run at full verbosity
without polluting the production log this phase just made more
informative (see get_account_balance()'s new WARNING/INFO lines).

Distinguishes between the five candidate root causes documented in
PATCH_NOTES.md for this phase:
  1. Futures wallet genuinely holds 0.00 USDT (funds elsewhere / tied
     up as isolated margin on an existing position).
  2. API key lacks Futures trading/read permission.
  3. Wrong environment (testnet keys vs live base URL or vice versa)
     -- note data/binance_provider.py's __init__ already refuses to
     start on an EXECUTION_MODE / BINANCE_TESTNET mismatch, so this
     script mainly confirms the resolved values match what Kaew
     expects, not that they're internally consistent.
  4. Binance Multi-Assets Mode changes the balance() response shape.
  5. Sub-account / master-account key mismatch.

Never prints API key material -- only which alias is in use and
whether it is set.
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    from config.settings import settings, EXECUTION_MODE

    print("=" * 70)
    print("Brain Bot -- Balance Diagnostic")
    print("=" * 70)

    print("\n[Environment]")
    print(f"  EXECUTION_MODE         = {EXECUTION_MODE}")
    print(f"  BINANCE_TESTNET        = {settings.BINANCE_TESTNET}")
    print(f"  base_url (resolved)    = {settings.base_url}")
    print(f"  SYMBOL                 = {settings.SYMBOL}")
    key_alias = "BINANCE_TESTNET_API_KEY" if settings.BINANCE_TESTNET else "BINANCE_API_KEY"
    key_value = settings.BINANCE_TESTNET_API_KEY if settings.BINANCE_TESTNET else settings.BINANCE_API_KEY
    print(f"  API key alias in use   = {key_alias}")
    print(f"  API key set?           = {'yes' if key_value else 'NO -- EMPTY'}")

    print("\n[Constructing BinanceDataProvider]")
    try:
        from data.binance_provider import BinanceDataProvider
        dp = BinanceDataProvider()
    except Exception as exc:
        print(f"  FAILED to construct BinanceDataProvider: {exc!r}")
        print("  (A RuntimeError here about EXECUTION_MODE/BINANCE_TESTNET")
        print("   mismatch, or empty mainnet credentials, IS the root cause --")
        print("   see data/binance_provider.py's __init__ for the exact check.)")
        return 1
    print(f"  trade_client.base_url  = {dp.trade_client.base_url}")
    print(f"  market_client.base_url = {dp.market_client.base_url}")

    print("\n[Raw trade_client.balance() response]")
    try:
        raw = dp.trade_client.balance(recvWindow=5000)
    except Exception as exc:
        print(f"  FAILED: {exc!r}")
        print("\n  A 401/403 here points at cause #2 (key lacks Futures")
        print("  permission) or cause #5 (key belongs to a different account).")
        return 1

    print(json.dumps(raw, indent=2, default=str))

    print("\n[Analysis]")
    if isinstance(raw, list):
        assets = [a.get("asset") for a in raw]
        print(f"  Asset entries returned: {assets}")
        usdt_entries = [a for a in raw if a.get("asset") == "USDT"]
        if not usdt_entries:
            print("  -> No 'USDT' entry at all in the response.")
            print("     Check Multi-Assets Mode on the account (cause #4 --")
            print("     it can change this response shape entirely), or")
            print("     confirm funds actually sit in the Futures wallet")
            print("     rather than Spot / a different account (causes #1, #5).")
        else:
            bal = usdt_entries[0].get("availableBalance")
            print(f"  -> USDT availableBalance = {bal}")
            if float(bal or 0.0) == 0.0:
                print("     Entry exists but is genuinely 0.00 -- check cause #1")
                print("     (funds elsewhere, or fully committed as isolated")
                print("     margin on an existing untracked position).")
            else:
                print("     Non-zero. get_account_balance() should already be")
                print("     returning this correctly with this phase's fix. If")
                print("     production still logs 0.00, diff this environment's")
                print("     .env / process env against the running bot's --")
                print("     they are pointed at different accounts or networks.")
    else:
        print(f"  Unexpected response type: {type(raw).__name__} (expected list)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
