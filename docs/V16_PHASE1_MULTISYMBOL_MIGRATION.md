# V16 Phase 1 — Multi-Symbol Foundation: Migration Notes

**Date:** 2026-07-17
**Base:** `brain_bot_v16_merged_fix1_fix2_p1a_p1b1.zip` (907 tests passing,
independently re-verified before this work started)

See `docs/architecture.md` §13 for the full architecture writeup. This
file is the practical "what do I need to do" companion.

## Do you need to change anything to deploy this?

**No**, if you're running a single symbol (the default). Everything below
is opt-in.

- `.env` / `config/settings.py`: no changes required. `SYMBOL=BTCUSDT`
  (or whatever you have) keeps working exactly as before.
- `main.py`: no changes required on your end — the one addition (a
  best-effort `initialize()` call) is already wired in and fails safe.
- `execution_factory.py`: no changes required — `build_execution_engine()`
  still takes the same arguments and returns an object with the same
  `.execute_trade(...)` signature.

## If/when you want to configure multiple symbols later

Set `SYMBOLS` as a JSON array in `.env`, e.g.:

```
SYMBOLS=["BTCUSDT","ETHUSDT"]
```

That alone makes `ExecutionCoordinator` create and manage a `TradeManager`
per symbol, and `initialize()` will set leverage/margin for each at boot.
**This does not, by itself, make the bot trade multiple symbols** — the
decision/risk/main-loop layers still operate on one symbol per cycle. That
wiring (Portfolio Manager) is explicitly future work — see architecture.md
§13 "Deliberately not done." Setting `SYMBOLS` today only prepares the
execution layer; don't set it expecting multi-symbol trading yet.

## Files changed

| File | Change | Risk |
|---|---|---|
| `config/settings.py` | +1 field (`SYMBOLS`), +1 property (`symbol_list`) | None — additive, defaults preserve old behavior |
| `execution/trade_manager.py` | `__init__` gains one optional `symbol` param | None — old call sites unaffected, verified by test + grep |
| `execution/execution_factory.py` | testnet/live build `ExecutionCoordinator` instead of bare `TradeManager`; `_PaperAdapter.execute_trade` gains an accepted-but-ignored `symbol` kwarg | Low — return type changes, but the interface (`.execute_trade(...)`) main.py depends on is identical; verified end-to-end |
| `main.py` | +1 guarded, best-effort `initialize()` call after building the execution engine | None — `hasattr` + `try/except`, non-fatal on any failure, trading loop itself untouched |
| `docs/architecture.md` | +2 sections (§13 new content, §14 renumbered "Next up") | Docs only |

## New files

- `execution/execution_coordinator.py` — the coordinator itself
- `tests/test_execution_coordinator.py` — 22 new tests
- `docs/V16_PHASE1_MULTISYMBOL_MIGRATION.md` — this file

## Regression summary (actually executed, not claimed)

```
$ pytest tests/ -q
```

| | Before this change (independently re-verified) | After this change |
|---|---|---|
| Passed | 907 | **929** |
| Failed | 0 | **0** |
| New tests | — | 22 (`tests/test_execution_coordinator.py`) |

Every pre-existing test still passes unmodified — no test file other than
the new one was touched. `pytest tests/ -v` output is reproducible; run it
yourself after unzipping to confirm.

## Design conflicts encountered

None that required stopping. One judgment call worth flagging explicitly:
the brief offered two options for the TradeManager refactor —
`place_market_order(symbol, ...)` (symbol-per-call) or "route through
coordinator" (symbol-per-instance, matching the `TradeManager(BTC)` /
`TradeManager(ETH)` diagram in the brief itself). These are different
designs. I chose symbol-per-instance because: (1) it's what the brief's
own architecture diagram shows, (2) it's a 2-line change to `TradeManager`
vs. threading a `symbol` parameter through eleven methods, and (3) it's
what "no shared mutable state" implies — a symbol-per-call design would
need `self.symbol` removed entirely and passed everywhere, which is a much
larger, riskier diff than "DO NOT rewrite it" allows for. If symbol-per-call
was actually intended, that's a different, larger change — flagging so
you can confirm before I'd build the alternative.

## No new dependencies

Confirmed — `execution_coordinator.py` uses only `threading` (stdlib) and
existing project imports.
