# MIGRATION — Entry guard (V16 §98)

## Required
None. No schema or API change.

## What you will notice
- A new entry on a symbol that already has an open exchange position is refused with `Entry refused: ... already has an open position`; the existing SL/TP are left untouched.
- New setting `ENTRY_EXISTING_POSITION_GUARD_ENABLED` (default `true`). Set `false` in `.env` to restore the previous behaviour.
