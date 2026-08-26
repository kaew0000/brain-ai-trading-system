# MIGRATION — V16 Phase 4C Track C: Multi-Symbol Rotation for the Background Training Lane

## Do you need to do anything?

**No — this phase is purely additive and off by default.** No settings
changed their existing meaning, no schema changed, no existing behavior
changed. If you don't set the new flag, the background training lane
keeps trading `settings.SYMBOL` only, exactly as it did before this
bundle.

## Opting in (optional)

To make the background training lane rotate across multiple
scanner-ranked symbols instead of one fixed one:

```
BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED=true
BACKGROUND_TRAINING_SYMBOL_POOL_SIZE=10          # optional, this is the default
```

Requirements for this to actually take effect:
- `SCANNER_ENABLED=true` (if the scanner isn't running, there's no
  ranked candidate list to rotate through — the lane silently falls
  back to its original fixed-symbol behavior, logged at DEBUG level,
  never an error).
- `BACKGROUND_PAPER_TRAINING_ENABLED=true` (or left unset — defaults to
  `true`) — the background lane has to be running at all for this to
  matter.

`BACKGROUND_TRAINING_SYMBOL_POOL_SIZE` controls how many top-ranked
candidates it round-robins through per full cycle of the pool — a
larger number means more dataset diversity but each individual symbol
gets revisited less often; a smaller number is closer to the old
single-symbol behavior but with a few alternates instead of one.

No database changes. No new dependencies. No frontend changes (Track A
only this phase).

## Rollback

Revert `paper/paper_execution.py`, `training_lane/training_lane_runner.py`,
`config/settings.py`, `main.py`, and delete the new test additions in
`tests/test_training_lane_runner.py`. If you set
`BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED=true` in `.env`, remove it (or
set it back to `false`) before rolling back the code — though leaving it
present after a rollback is also harmless, since the reverted code
simply won't read it.

## What this does not fix

See `PATCH_NOTES.md`'s "What this does not fix / does not do" for the
full list of deliberate, reasoned-through scope boundaries.
