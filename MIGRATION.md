# MIGRATION — Fix: Live Account Balance Reads 0.00 USDT

## Do you need to do anything?

**Yes — one action required to actually diagnose the live problem.**
This bundle does not (and cannot, from this sandbox) fix the root
cause; it makes it observable and gives you a tool to find it.

## Step 1: Import this bundle, restart the bot

No settings changed, no schema changed, no existing behavior changed
for anything that was already working. `get_account_balance()` returns
the exact same values it always did — the only change is that the
previously-silent "no USDT entry found" path now logs a `WARNING`
instead of nothing, and a successful read now logs at `INFO` instead
of `DEBUG`. Safe to import and restart with zero behavior risk.

## Step 2: Run the diagnostic script against your live-configured account

```
python scripts/diagnose_balance.py
```

Run this with the **same `.env`** the live bot uses (same
`BINANCE_TESTNET`, same API keys). It prints:
- Resolved `EXECUTION_MODE`, `BINANCE_TESTNET`, `base_url`, which API
  key alias is active, and whether it's set (never the key itself).
- The full raw `trade_client.balance()` response.
- An analysis pointing at which of the 5 candidate causes (documented
  in `PATCH_NOTES.md`) the response is consistent with.

## Step 3: Report back what it shows

Paste the script's output (redact nothing except you already don't
need to — no key material is ever printed) so the actual fix can be
scoped. The five candidate causes need different fixes — a parsing
change, a `.env` value, or a Binance-side API key permission change
that no code change can address — so this phase deliberately stops
here rather than guessing.

## New file: `scripts/`

This is the first file in a `scripts/` directory — none existed
before this phase. Future one-off operator scripts should live here.
