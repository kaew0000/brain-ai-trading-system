# MIGRATION — Fix: ExecutionCoordinator Rejects Scanner-Discovered Symbols

## Do you need to do anything?

**No — this is off by default.** Importing this bundle and restarting
the bot changes nothing about current behavior. Scanner-discovered
symbols outside `settings.symbol_list` will continue to fail exactly as
before (`Symbol 'X' is not configured on this coordinator`) until you
explicitly opt in.

## To actually let the coordinator trade scanner-discovered symbols

Add to `.env`:

```
EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS=true
```

Optional — override the default cap of 50 (see PATCH_NOTES.md for why
this cap exists and how 50 was chosen):

```
EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS=50
```

Restart the bot. From then on:

- A scanner-discovered symbol outside the originally-configured list
  gets registered automatically on first use, up to the cap.
- `logs/brain_bot.log` gets an INFO line each time:
  `ExecutionCoordinator: dynamically registering new symbol 'X' ...`
- Once `max_dynamic_symbols` distinct new symbols have been registered
  in this run, any further genuinely-new symbol gets the same
  `ValueError` as before this phase (now mentioning the cap explicitly)
  — this resets on the next restart (the list is in-memory only).

## What this does NOT change

- The originally-configured `symbol_list` behavior — unaffected either
  way.
- `main.py`'s startup pre-warming (`initialize()`) — still only
  pre-warms the statically-configured symbols. A dynamically-registered
  symbol's leverage/margin get set on its own first trade instead (this
  is how the code has always worked for every call, not something new).
- Nothing about `MarketScanner` or `OpportunityRanker`.

## If you want this on but want a tighter/looser cap

`EXECUTION_COORDINATOR_MAX_DYNAMIC_SYMBOLS` is independent of
`EXECUTION_COORDINATOR_DYNAMIC_SYMBOLS` — set both together in `.env`.
Setting the cap without the flag has no effect (ignored when the flag
is off).
