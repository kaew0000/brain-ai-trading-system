# PATCH NOTES — SCHEDULER_ENABLED Implies Dynamic Symbols (V16 §61)

Branch: `fix/scheduler-implies-dynamic-symbols`
Base: `main` @ `2c7ac33` (merge of PR #96, multi-symbol scheduler
safety — rebased onto this after that PR merged; originally written
against `e59e340`/pre-§60, see git history for the rebase).

## Root cause

Found while writing §60's own MIGRATION.md: telling an operator to set
`SCANNER_ENABLED=true` + `SCHEDULER_ENABLED=true` and nothing else was
**incomplete**. Traced the actual execution path all the way through:

```
MarketScanner  → discovers candidates across the full Binance universe
                 (execution/execution_coordinator.py's own module
                 docstring), filtered only by SCANNER_MIN_QUOTE_VOLUME
                 (24h liquidity), not by any pre-configured symbol list
CapitalManager → selects from those candidates
ExecutionOrchestrator → calls execution_engine.execute_trade(symbol=alloc.symbol, ...)
ExecutionCoordinator.get_manager(symbol) → if symbol not in self._symbols
                 and not self._allow_dynamic_symbols: raise ValueError(...)
```

`settings.symbol_list` (the coordinator's pre-configured `_symbols`)
defaults to `[settings.SYMBOL]` = `["BTCUSDT"]` when `SYMBOLS` is
unset. `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` (the flag that lets the
coordinator register a `TradeManager` for a symbol it wasn't
pre-configured with) defaults `False`, **independently** of
`SCHEDULER_ENABLED`. Net effect: with only `SCANNER_ENABLED` +
`SCHEDULER_ENABLED` set (exactly what §60's MIGRATION.md said to do),
every trade attempt in any symbol other than BTCUSDT would hit
`get_manager()`'s `ValueError` and fail. Not a silent-wrong-execution
bug — it fails loud and safe — but it means the multi-symbol scheduler
this project just spent two phases making safe to enable would not,
in fact, trade more than one symbol without a third, undocumented flag.

## Fix

`execution/execution_factory.py::build_execution_engine()` —
`allow_dynamic_symbols` is now `settings.EXECUTION_COORDINATOR_
DYNAMIC_SYMBOLS or settings.SCHEDULER_ENABLED` instead of reading the
first flag alone. Rationale: turning on "trade every symbol the
scanner finds" is the entire point of `SCHEDULER_ENABLED` — requiring
a separate, undiscovered flag just to make that actually work is a gap
in what operators need to know, not a deliberate extra safety gate
(unlike `SCHEDULER_ENABLED` itself, which legitimately is one).

An operator who wants the opposite — scheduler on, but strictly
confined to a fixed symbol list — already has that path today: set
`settings.SYMBOLS` explicitly. Dynamic registration only ever *adds*
symbols beyond the configured list; it doesn't override or bypass it.

## Tests

`tests/test_execution_factory.py` — 2 new tests:
- `test_scheduler_enabled_implies_dynamic_symbols_even_when_flag_left_off`
  — the fix, directly.
- `test_scheduler_disabled_and_flag_off_still_confines_to_configured_symbols`
  — the reverse case pinned explicitly, so this OR can never silently
  widen the default posture for a deployment that isn't using the
  scheduler at all.

Both pre-existing dynamic-symbol tests (`test_testnet_dynamic_symbol_
settings_default_off`, `test_testnet_wires_dynamic_symbol_settings_
through_when_enabled`) pass unchanged — neither touches
`SCHEDULER_ENABLED`, so the `or` term stays `False` for them, same
result as before.

Full suite: `pytest tests/` → **3068 passed** (base 3066 from §60 + 2
new), 4 skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` on the changed source file → 3 pre-existing,
unrelated findings only (`_PaperAdapter.execute_trade`'s
`balance`/`leverage`/`symbol` params, accepted for interface parity
and intentionally not forwarded — confirmed identical against
unmodified `main`, just shifted line numbers from this patch's added
comment block). `python -c "import main"` → succeeds.

## Files changed

`execution/execution_factory.py`, `tests/test_execution_factory.py`,
`PATCH_NOTES.md`, `MIGRATION.md`, `CHANGELOG.md`,
`docs/architecture.md` (§61).
