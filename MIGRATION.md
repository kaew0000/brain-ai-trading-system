# MIGRATION — Test/Tooling Housekeeping Batch (V16 §70, renumbered from §68 — see PATCH_NOTES.md)

## Do you need to do anything?

**No.** Both fixes in this batch are test/tooling-only:

- `tests/test_execution_factory.py`'s fixture change only affects test
  execution — no production code path is touched, no settings
  behavior changes, nothing to configure.
- `bundle_history.json`'s new `corrected_sha`/`correction_note` fields
  are additive and optional (default `None`). Any tool or script
  reading this file that doesn't know about the new fields continues
  to work exactly as before — `tools/history.py`'s own loader already
  handles their absence via `.get()`.

No database migration, no `.env` changes, no rollback considerations
beyond a normal `git revert` if ever needed.
