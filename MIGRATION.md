# MIGRATION — SCHEDULER_ENABLED Implies Dynamic Symbols (V16 §61)

## Do you need to do anything?

**No, if `SCHEDULER_ENABLED` is `false` (the default).** Nothing
changes — `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` still defaults
`False`, and `False or False` is still `False`.

## If you're enabling multi-symbol trading (§60 + this patch)

This **replaces** a step §60's own MIGRATION.md told you to do
manually. You no longer need to separately set
`EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS=true` — setting
`SCHEDULER_ENABLED=true` now implies it automatically. The full
`.env` needed is just:

```bash
SCANNER_ENABLED=true
SCHEDULER_ENABLED=true
```

If you already added `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS=true`
manually after reading §60's notes, it's harmless to leave it — the
`or` makes either one sufficient.

## If you want the scheduler confined to specific symbols

Set `SYMBOLS` explicitly instead of relying on the default, e.g.:

```bash
SYMBOLS=["XRPUSDT","DOGEUSDT","ADAUSDT"]
```

This still works exactly as before — dynamic registration (now
automatic under `SCHEDULER_ENABLED=true`) only ever *adds* symbols
beyond this list as the scanner discovers new candidates, up to
`EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS` (default 50). It does not
restrict or override an explicit `SYMBOLS` list.

## Rollback

Revert this branch and restart. `allow_dynamic_symbols` goes back to
reading only `EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` — you'd need to
set that flag explicitly again for multi-symbol trading to actually
execute trades outside the default symbol.
