# MIGRATION — Logging Subsystem Hotfix: Shared RotatingFileHandler

## Do you need to do anything?

**No.** This is an internal implementation change inside
`utils/logger.py` only. `get_logger(name)` keeps the exact same
signature and return type (a standard `logging.Logger`), and every one
of the ~83 existing call sites (`get_logger(__name__)`) needs no
change. No config flag, no `.env` key, no schema change, no import
added to any file outside `utils/logger.py` and the new test file.

## What actually changed, mechanically

Before: every distinct logger name got its own
`RotatingFileHandler(cfg.LOG_FILE, ...)` instance — N names meant N
open file handles on the same log file.

After: one shared `RotatingFileHandler` instance is created lazily on
first use and reused for every logger name — exactly 1 open file
handle on the log file, no matter how many modules call `get_logger()`.

This is why the Windows rotation was failing: `os.rename()` (used
inside `doRollover()`) fails if any *other* handle on the same process
still has the file open, and there were always dozens of others. With
one shared handle, `doRollover()` closes it, renames cleanly, reopens
it — no competing handle to block the rename.

## Rollback

Revert `utils/logger.py` to the previous inline
`RotatingFileHandler(...)` construction inside `get_logger()`, and
delete `tests/test_logger.py`. Nothing else references the shared
handler internals (`_file_handler`, `_get_shared_file_handler`) — they
are private module state, not imported anywhere else in the codebase.

## What this does not fix

- It does not recover any log lines lost during the affected session
  (they were dropped before the file write happened; nothing to
  recover from disk).
- It does not address the two other issues reported from the same
  session (live-confirmation-vs-actual-mode mismatch, startup
  reconciliation mismatch) — those are separate, not touched here.
