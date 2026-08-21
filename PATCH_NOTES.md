# PATCH NOTES — Fix: Live Account Balance Reads 0.00 USDT (Blocks Every Trade)

Branch: `fix/live-balance-zero-diagnostics`
Base: `main` @ `ba47800` (merge of PR #71, Symbol-Aware SMC/OI Regime Strategy Adapter)

## Scope note

Requested via an uploaded phase brief (`01_fix_live_balance_reads_zero.md`):
the live bot has never opened a single order despite the AI pipeline
correctly producing LONG/SHORT decisions at 60–77% confidence,
repeatedly, over a 30+ hour production log — diagnose and fix why
`get_account_balance()` returns `0.0`, and make the failure loud
instead of silent.

Track A only (Python backend). No `dashboard_src/` changes.

## Root cause

`data/binance_provider.py`'s `get_account_balance()` — confirmed
unchanged from the brief's description by re-reading the file — loops
over `trade_client.balance(recvWindow=5000)`'s response looking for an
`"asset" == "USDT"` entry. If the loop completes without finding one,
it silently `return 0.0` with **no log line at any level**. The one
existing log line on the success path was `logger.debug(...)`, and the
brief's production log is INFO level — so even a *successful* non-zero
balance read would never have appeared in it either. Net effect: this
code path was completely invisible in `logs/brain_bot.log` whether it
was succeeding or silently failing.

Downstream, `execution/trade_manager.py` is working correctly: given
`balance=0.00`, `risk_pct × 0.00 = 0`, quantity rounds to `0.0`, which
is below Binance's `minQty` (0.001 BTC for BTCUSDT), so it correctly
and safely refuses to size the trade. **The bug is entirely upstream of
trade_manager.py**, in how balance is obtained — confirmed by reading
`execute_trade()`'s qty-rounding logic, not assumed.

## Why this phase stops after Step 1/2 (does not identify *which* of
## the 5 candidate causes it is)

This sandbox has no network path to Binance's API (egress allowlist
covers GitHub/PyPI/npm only — no `binance.com`), so
`trade_client.balance()` cannot actually be called here. The five
candidate causes the brief lists (empty Futures wallet, API key
permissions, testnet/live key mismatch, Multi-Assets Mode response
shape, sub-account mismatch) require inspecting a **real** raw
response, which only Kaew's environment can produce. This matches the
brief's own instruction: *"Stop after Steps 1-2 and report findings
unless the raw response is already available to inspect in this
session."* It was not. Steps 1 and 2 are complete; Step 3 (the actual
parsing/config fix) is deliberately not attempted — guessing at which
of five semantically-different fixes applies without the real response
would risk masking the actual problem, which the brief explicitly warns
against.

One thing this phase *could* confirm by reading code alone: cause #3
(wrong environment) is already partially guarded — `BinanceDataProvider.__init__`
raises a `RuntimeError` at startup if `EXECUTION_MODE` and
`BINANCE_TESTNET` disagree (`BUG-V16-BP-05`, V16 Phase 2.x). Since the
bot evidently *started* and ran 30+ hours logging decisions, that guard
did not fire — narrowing cause #3 to "keys generally point at the right
network" but not ruling out a keys-valid-but-wrong-account variant
(cause #5), which that guard cannot detect.

## What changed

| File | Change |
|---|---|
| `data/binance_provider.py` | `get_account_balance()`: the silent `return 0.0` fallback now logs a `WARNING` first, including the list of asset names actually returned (never balance figures — none were found on this path anyway). The success-path log promoted from `logger.debug` to `logger.info` so a healthy non-zero read is visible in a normal INFO-level production log too. No control-flow change — same return values, same exceptions, same retry/circuit-breaker behavior. |
| `scripts/diagnose_balance.py` (new) | Standalone operator script (no `scripts/` directory existed before this phase — created it). Constructs the same `BinanceDataProvider` `main.py`'s `build_system()` does (no factory to duplicate — it's a direct one-line construction there), prints the resolved environment (`EXECUTION_MODE`, `BINANCE_TESTNET`, resolved `base_url`, which API key alias is in use and whether it's set — never the key material), then calls `trade_client.balance()` directly and prints the full raw response plus an analysis pointing at which of the 5 candidate causes it's consistent with. Run manually; never called from the trading loop; never logs to `logs/brain_bot.log`. |
| `tests/test_balance_zero_diagnostics.py` (new) | 3 tests: no-USDT-entry logs a `WARNING` and returns `0.0`; empty-list response (Multi-Assets Mode shape change, cause #4) logs a `WARNING` and returns `0.0`; a genuine USDT entry logs at `INFO` (not just `DEBUG`) and returns the correct float. Asserts the log call happened, not its exact wording, per the brief's instruction. Mirrors `tests/test_binance_provider_trade_client.py`'s fixture style (`mock_time` avoids a real network call in `__init__`'s `_sync_time_offset()`; settings monkeypatched the same way). |

**Not touched** (per phase scope): `execution/trade_manager.py`'s
position-sizing/qty-rounding logic, `RISK_PER_TRADE_MIN`/`MAX`,
`CONFIDENCE_TRADE_THRESHOLD` — none are related to this bug.

## Testing

- `pytest tests/`: **2626 passed**, 45 deselected (integration marker),
  3 failed — all 3 pre-existing and unrelated
  (`tests/test_dashboard_serving.py`, blocked on the missing
  `dashboard_src/dist` build artifact in this sandbox).
  Verified true baseline via `git stash` (tracked-file changes only —
  new test file stays untracked/present, so it fails without the fix
  applied, confirming it actually exercises the change): `main` @
  `ba47800` unmodified = 2623 passed / 3 failed (same 3 dashboard
  tests). With this phase's fix applied, the same 3 new tests flip to
  passing = 2626 passed, zero regressions elsewhere.
- `ruff check . --exclude dashboard_src --exclude dashboard`: clean,
  before and after.
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80`:
  0 findings.
- `python3 -c "import main"`: OK.
- `scripts/diagnose_balance.py`: syntax/compile-checked
  (`py_compile`); **not** run end-to-end — would require a real
  Binance network path this sandbox does not have. Kaew should run it
  directly against the account the live bot uses.
- Frontend: not touched this phase (Track A only).

## What this does not fix / does not do

- Does **not** identify which of the 5 candidate root causes is
  actually occurring — that requires running
  `scripts/diagnose_balance.py` against the real, live-configured
  account and reporting back the raw response.
- Does **not** change `execute_trade()` / position-sizing / rounding —
  that logic is correct and untouched.
- Does **not** guess at or apply a parsing/config fix for Step 3. Once
  the raw response is available, the actual fix (if any code change is
  even needed — cause #2/#5 may require a Binance-side API key change,
  not a code change) should be scoped as its own follow-up phase.
