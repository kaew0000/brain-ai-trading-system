# PATCH NOTES — Logging Subsystem Hotfix: Shared RotatingFileHandler

Branch: `fix/logger-shared-file-handler`
Base: `main` @ `90a2874` (rebased — `origin/main` advanced past the
original `f7e9caf` base via PR #53 W14-1 and PR #54 W14-2A while this
branch was in flight; rebased cleanly onto current `main` with a single
conflict in `docs/architecture.md` — both branches appended a new
numbered section after §36. Resolved by keeping W14-2A's entry as the
canonical §37 and renumbering this hotfix's entry to §38. No other
file conflicted — W14-1/W14-2A never touched `utils/logger.py`,
`tests/test_logger.py`, `PATCH_NOTES.md`, or `MIGRATION.md`.)

## Scope note

This is not a numbered phase — it's a hotfix for a production incident
reported directly from a live/paper run's console output, not from a
task brief. No existing documentation (architecture.md, CLAUDE.md)
described this as planned work; it was discovered and fixed reactively.

## Root cause

`utils/logger.py::get_logger(name)` is idempotent **per logger name**
(`if logger.handlers: return logger`), but every one of the ~83 distinct
call sites in this codebase (`get_logger(__name__)` in `main.py`,
`data/binance_provider.py`, `risk/risk_engine.py`, `events/event_bus.py`,
etc.) passes a *different* name. Each of those ~83 first-time calls
independently constructed its own `logging.handlers.RotatingFileHandler`
pointed at the same `cfg.LOG_FILE` path (`logs/brain_bot.log`).

That left ~83 separate, simultaneously open OS file handles on one file,
all owned by the same process. `RotatingFileHandler.doRollover()` closes
*its own* stream, then calls `os.rename(source, dest)`. On Windows,
`os.rename()` fails with `PermissionError: [WinError 32]` if *any other*
handle still has the file open — and 82 other handlers always did. Once
the file crossed `maxBytes` (10 MB), every logger's next `emit()` call
re-triggered `shouldRollover() → True → doRollover() → raise`, and
because the raise happens *before* `logging.FileHandler.emit()` actually
writes the record, **every log line for the rest of the process's life
was silently dropped from `brain_bot.log`** (visible only via the
`--- Logging error ---` traceback printed to stderr).

Confirmed mechanically (not just by inference from the traceback):
constructing N `RotatingFileHandler` instances on one path produces N
distinct `id(handler.stream)` values; the fix collapses this to exactly
1 by construction. (`WinError 32` itself can't be reproduced from this
Linux environment — POSIX allows rename of an open file — so the fix
was verified by proving the underlying mechanism, multiple concurrent
handles on one path from a single process, is eliminated, not by
reproducing the Windows error text itself.)

## Fix

`utils/logger.py`: added a module-level, lock-guarded singleton
(`_get_shared_file_handler()`) that lazily creates **one**
`RotatingFileHandler` on first use and returns that same instance to
every subsequent caller regardless of logger name. `get_logger()` now
calls this shared accessor instead of constructing a fresh handler
inline. Console handler behavior (per-name, colorized) is unchanged.

No signature change, no new config, no behavior change for any of the
83 call sites — they still just call `get_logger(__name__)`.

## Files changed

- `utils/logger.py` — shared file handler singleton (the fix)
- `tests/test_logger.py` — new regression tests (see below)

## Test results (post-rebase, against current `main` @ `90a2874`)

- `pytest tests/test_logger.py -v` → 4 passed (new)
- Full `pytest tests/ -q` → 2538 passed, 3 failed, 5 warnings
- `pytest world/tests/ -q -m ""` → 565 passed (unchanged)
- `ruff check . --exclude dashboard_src --exclude dashboard` → clean
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80` → clean
- `python3 -c "import main"` → clean

The 3 `tests/test_dashboard_serving.py` failures are **pre-existing on
`main` itself**, unrelated to this change — confirmed by running the
identical command on `origin/main` before rebasing: 2534 passed / 3
failed, same 3 tests. They fail in this sandbox because
`dashboard_src/dist/index.html` doesn't exist (no `npm run build` was
run here; W14-1's CI job builds it as a separate pre-test step). 2538
− 2534 = the 4 new tests added here, cleanly. Nothing regressed.

Original baseline (captured before the rebase, against the
then-current `main` @ `f7e9caf`, before W14-1/W14-2A existed): 2480
passed / 565 passed / ruff clean / vulture clean / import clean — also
matched exactly plus the 4 new tests.

## Known follow-up work (explicitly out of scope for this hotfix)

- The production log file (`logs/brain_bot.log`) from the affected
  session is effectively empty for the run in question — this fix
  prevents recurrence, it does not recover lost historical log data.
- Not investigated here (separate reported issues, tracked
  separately): the live-confirmation-vs-actual-mode banner mismatch,
  and the startup reconciliation mismatch on a pre-existing exchange
  position.
- `CHANGELOG.md` remains stale (pre-existing, previously flagged gap;
  not touched by this hotfix, consistent with how it's been handled in
  prior phases).
