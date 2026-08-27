# PATCH NOTES — V16 Phase 4C §49: Training Lane Restore-on-Restart

Branch: `feat/training-lane-multi-symbol-rotation` (this is the **second commit**
on this branch — the first, already delivered, was the multi-symbol
rotation phase; both are part of the same PR)
Base: `main` @ `9ddd9d6` (merge of PR #78)

## Scope note

Requested directly: "แก้ให้ต่อของเดิมที่เทรนค้างได้" — every process
restart threw the background training lane's whole in-memory state
away. A fresh $100 `PaperAccount` every time, and — worse — any
genuinely open position simply vanished: that trade's eventual
WIN/LOSS outcome was never captured at all, silently dropped, no error,
no log. Given how often this bot has restarted throughout this thread
(crash-looking restarts, manual restarts, dashboard-driven confusion
now separately fixed), this was a real, recurring loss of training
continuity, not a theoretical edge case.

Delivered as a second commit on the rotation branch rather than a new
sibling branch: both touch `training_lane_runner.py`'s `_cycle()`/
`__init__` significantly, and stacking avoids a real code-level merge
conflict Kaew would otherwise have to resolve by hand. Import/merge
this bundle as one PR containing both commits.

Track A only (Python backend). No `dashboard_src/` changes.

## Context

`TrainingLaneRunner._new_engine()` always did
`PaperAccount(balance=self._starting_balance)` — no loading from
anywhere. `PaperAccount`'s own module docstring says "no DB
dependency," which was true and remains true; the module was simply
never given anything to load from in the first place.

## What changed

| File | Change |
|---|---|
| `paper/paper_account.py` | `+to_state_dict()`/`+from_state_dict()` — full internal state (balance, margin, trade counts, day-PnL tracking, a capped equity-curve tail), not just the read-only display fields `to_dict()` already exposed. `from_state_dict()` is defensive against missing **and malformed** fields (a dedicated test caught an early version of this that still raised on a garbage string value — fixed before delivery, not after). |
| `paper/paper_position.py` | `+to_state_dict()`/`+from_state_dict()` on `PaperPosition` — includes `opened_at` and `bars_open` (not just the entry/SL/TP/quantity fields) so a restored open position keeps an accurate `TIMEOUT_BARS` countdown and accurate `duration_s` when it eventually closes, rather than silently resetting either. Deliberately raises on missing required fields (unlike the account's version) — the caller catches this per-position. |
| `paper/paper_execution.py` | `+to_state_dict()`/`+from_state_dict()` on `PaperExecutionEngine` — account plus any open position(s). Deliberately does **not** persist `self._closed` (this session's in-memory closed-trade cache) — the durable closed-trade record already lives in `research/dataset_builder.py`'s captured rows regardless; restoring the in-memory cache too would be redundant, not a source of truth. |
| `database/schema_v13.sql` | `+training_lane_state` table — single-row (`CHECK (id = 1)`), one opaque JSON blob column. Deliberately not normalized into typed columns: nothing ever queries into this blob's fields with SQL, and the blob's shape is owned by the three classes' own `to_state_dict()` methods, not by this schema. |
| `training_lane/state_store.py` (new) | `TrainingLaneStateStore` (thin `ManagedConn`-per-call wrapper, mirrors `research/feature_store.py`'s pattern) plus `get_training_lane_state_store()`/`reset_training_lane_state_store()` singleton accessors (mirrors `get_dataset_builder()`/`get_trade_journal_v2()`'s established pattern). |
| `training_lane/training_lane_runner.py` | `__init__` attempts `_restore_state()` right after building the fresh engine — replaces it only on a clean restore, never raises, never a precondition to run. `_cycle()` calls `_save_state()` at the end **every cycle** (not just on a graceful `stop()`) — deliberate: this project's restarts have far more often looked like a closed terminal than a clean Ctrl+C, so "never more than one cycle stale" only holds if saving doesn't depend on a graceful exit path. New `status()` field: `restored_from_prior_run`. |

**Not touched**: `paper/paper_execution.py`'s `tick()`/`execute()` core
logic, `PaperPosition`'s SL/TP/timeout logic — all unchanged; this
phase is purely about what gets reconstructed at startup, not how any
of it behaves once running.

## A real bug this phase's own tests caught before delivery

`PaperAccount.from_state_dict()`'s first draft called `float(...)`/
`int(...)` directly on saved fields with no exception handling around
the coercion itself — a genuinely corrupted saved value (e.g.
`"balance": "not-a-number"`) would raise immediately, contradicting the
method's own documented "never raises" contract.
`TestPaperAccountStateRoundtrip::test_from_state_dict_never_raises_on_garbage_values`
caught this before delivery; fixed with small `_f()`/`_i()` safe-coercion
helpers used throughout.

## Testing

- `pytest tests/`: **2863 passed** (2842 true baseline on this branch,
  independently re-measured via `git stash -u` — 2842 + 21 new = 2863
  exactly), 0 failed, 45 deselected.
- 13 new tests in `tests/test_training_lane_runner.py`
  (`TestRestoreOnRestart`, 8; `TestPaperAccountStateRoundtrip`, 3;
  `TestPaperPositionStateRoundtrip`, 2) — covers: nothing-to-restore on
  first run, a flat account surviving a restart, an **open position**
  surviving a restart with all fields intact, that a restored position
  can still genuinely close (hit TP) exactly as if never restarted, bust
  count and rotation index surviving a restart, corrupted saved state
  and a state-store I/O failure both falling back to a fresh account
  without raising, and the new `status()` field.
- 8 new tests in `tests/test_training_lane_state_store.py` — save/load
  roundtrip, overwrite-not-duplicate (single-row enforcement), two
  store instances against the same file seeing each other's writes,
  I/O-failure-never-raises for both save and load, and the singleton
  accessor.
- **Also had to fix a real test-isolation bug found while writing these
  tests**: `_make_runner()`'s test helper, before this phase, had no
  `state_store` parameter at all — adding restore-on-construction meant
  every existing test in the file (which never expected persistence)
  started silently sharing the real production `db_path`'s singleton
  store, causing one test's saved state to leak into and corrupt the
  next test's "fresh" runner. Fixed with a `_NoOpStateStore` test fake
  now used as `_make_runner()`'s default, so persistence stays fully
  opt-in per test — every pre-existing test in the file was re-verified
  passing after this fix, not just the new ones.
- `ruff check .`: clean. `vulture . --min-confidence 80`: 0 findings.
  `python3 -c "import main"`: OK.
- Independent second-clone verification: see delivery message.

## What this does not fix / does not do

- Does not persist `PaperExecutionEngine._closed` (in-memory closed-trade
  cache) or `PaperAccount`'s full unbounded equity curve (capped to the
  most recent 500 points) — neither is the source of truth for training
  data (that's `research/dataset_builder.py`'s durable rows, already
  safe regardless of this phase), so this was a deliberate scope
  boundary, not an oversight.
- Does not persist anything about the *live* lane — this phase is
  entirely about the background training lane's own continuity.
- Does not add a migration script — `training_lane_state` is a purely
  additive new table; `database/db.py`'s existing `_apply_schema()`
  (idempotent `CREATE TABLE IF NOT EXISTS`, applied on every connection)
  already creates it automatically for both fresh and existing
  databases, including Kaew's live one, with no separate step needed.
