# PATCH NOTES — Commission/Fee Backfill (V16 §67)

Branch: `feat/fee-capture-backfill`
Base: `main` @ `0b5dc82` (merge of PR #102, multi-symbol ghost reconciliation)

Closes the "fee capture" item from the 2026-08-05 project tracker's
Risk Register (still open as of that snapshot, re-verified still open
against current `main` before starting this phase).

## Root cause

Binance Futures market-order responses never include commission
(confirmed against Binance's own REST API reference for `POST
/fapi/v1/order`). `execution/execution_orchestrator.py`'s
`open_confirmed()`/`exit_confirmed()` calls have accepted a `fees`
parameter since Phase 4B Step 2 (§29), but no caller has ever fetched
a real value to pass — `fees` has always been `None` in every trade's
`extra_data.attribution`, understating realized P&L in
`journal.get_trade_attribution()`/`get_ensemble_learning_dataset()`.

## Design

Background-only, read-only against the exchange, single write path
(`journal.save_execution_attribution()`, the same merge-only method
every other execution-attribution field already uses). Deliberately
does not touch the live open/close code paths at all — runs entirely
after the fact on a schedule, same shape as
`system_health/reconciliation.py`'s position reconciliation.

Two design options were surfaced and confirmed with the repo owner
before implementation: (A) synchronous fetch right after each fill, or
(B) background backfill job. **(B) was chosen** — it adds zero
latency/failure-risk to the live order path, and one call site
(`main.py`'s classic-loop TP/SL exit detection) never has a close
`orderId` to fetch against in the first place, so (A) couldn't have
covered it either way.

**Entry vs. exit fees — a real, permanent limitation, not a bug.**
Entry fee is recoverable for every trade (`trades.order_id` is always
captured at open). Exit fee is only recoverable where a close
`orderId` was captured — only true for the multi-symbol scheduler's
replacement-close path, not the classic single-symbol loop's
mark-price-heuristic close. This module never fuzzy-matches by
symbol+time window to fill that gap — same "documented gap over
fabricated inference" principle `system_health/recovery_engine.py` and
the `bundle_history.json` Phase 2E record already follow elsewhere.

**Scheduler-thread safety.** Runs in `main.py`'s single scheduler
thread alongside every other `schedule.every()` job, so it makes at
most one attempt per Binance API call (no exponential-backoff retry)
and bounds candidates per run (`FEE_BACKFILL_MAX_TRADES_PER_RUN`,
default 50).

## Implementation

- `config/settings.py` — `FEE_BACKFILL_ENABLED` (default `False`),
  `FEE_BACKFILL_INTERVAL_MINUTES` (default 15),
  `FEE_BACKFILL_LOOKBACK_HOURS` (default 24),
  `FEE_BACKFILL_MAX_TRADES_PER_RUN` (default 50).
- `journal/journal_v2.py` — new `get_trades_missing_fees(since_iso,
  limit)`.
- `journal/fee_backfill.py` (new) — `backfill_commission_fees(journal,
  client)`, `_sum_commission()`, `_fetch_order_commission()`.
- `main.py` — new `run_fee_backfill_job(sys)`, scheduled
  unconditionally via `schedule.every(settings.
  FEE_BACKFILL_INTERVAL_MINUTES).minutes.do(...)`, no-ops when the
  flag is off.
- `docs/architecture.md` §67, `CHANGELOG.md`, `MIGRATION.md`, this
  file.

## Tests

New: `tests/test_fee_backfill.py` — 17 tests covering
`get_trades_missing_fees()`'s candidate filtering, `_sum_commission()`'s
single-asset/mixed-asset/malformed-input handling, and
`backfill_commission_fees()`'s disabled/missing-dependency no-ops,
entry-only fill, entry+exit fill, never-fetch-exit-without-close-
order-id, API-error handling, and mixed-asset-order handling. Uses a
fake `UMFutures`-shaped client — no real Binance API calls in tests.

All 3124 pre-existing tests pass unchanged.

Full suite: `pytest` → **3141 passed** (up from 3124), 4 skipped, 45
deselected, **0 failures** — the "3 pre-existing dashboard-build
failures" cited in every phase since §55 are not a real bug (see
Correction below); this run built `dashboard_src/dist/` first, as CI
already does, and got 0 failures.

`ruff check . --exclude dashboard_src --exclude dashboard` → all
checks passed, repo-wide. `vulture . --exclude
dashboard_src,dashboard,tests --min-confidence 80` → clean, no new
findings. `python -c "import main"` → succeeds.

## Correction to every prior phase's test-count note (§55–§66)

The "3 pre-existing dashboard-build failures" repeatedly cited since
§55 turned out not to be a real bug:
`tests/test_dashboard_serving.py` needs `dashboard_src/dist/` to
exist, which is gitignored and absent on a fresh clone until `npm run
build` runs — CI already builds the dashboard before `pytest` for
exactly this reason. This phase's verification built the dashboard
first and got 0 failures. No dashboard-serving code changed in this
phase; this is a correction to the historical record, not a fix.

## Files changed

`config/settings.py`, `journal/journal_v2.py`, `journal/fee_backfill.py`
(new), `main.py`, `tests/test_fee_backfill.py` (new), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`, `docs/architecture.md` (§67).
