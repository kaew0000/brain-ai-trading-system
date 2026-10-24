# PATCH NOTES — close stale N+1 roadmap item; add dataset read benchmark (V16 §77)

Branch: `fix/learning-dataset-n-plus-1`
Base: `main` @ `ec67c57` (PR #114 merged)
Commit: `docs(learning): close stale N+1 roadmap item; add dataset read benchmark (V16 §77)` (exactly one)

## Root cause

Not a performance bug — a stale roadmap. `get_ensemble_learning_dataset()`'s N+1 read pattern was **fixed at V16 §63
(`a702c27`, 2026-09-12)**: one `trades` query + one `agent_decisions` query (`signal_id IN (...)`) regardless of `limit`, shared
row shaping via `_shape_trade_attribution()`, locked by `tests/test_ensemble_dataset_bulk_fetch.py`. `docs/ROADMAP.md`
(Planned), `CLAUDE.md` (Current Priorities item 5) and a docstring in `learning/application/recommendation_context.py` kept
describing it as open. Re-measured on `main` @ `ec67c57` before touching anything (docs/architecture.md §77):

| trades | read | SQL statements | old per-trade shape (reference) |
|---:|---:|---:|---:|
| 100 | 4.9 ms | 7 | 71.5 ms |
| 1,000 | 47.7 ms | 7 | 1,097.7 ms |
| 5,000 | 269.2 ms | 7 | 11,607.6 ms |

Constant statement count, flat ~0.05 ms/trade, 5,000 trades ~0.3 s. No fix is needed, so no before/after is claimed.

## Changes (no behavior change)

- `tools/benchmark_ensemble_dataset.py` (new): populates a temp journal via the real write API, measures read latency and SQL
  statement count at 100/1,000/5,000 trades; `--check` exits 1 on N+1 (statement count varies), wrong row count, or
  super-linear per-trade cost; `--json`, `--with-reference`.
- `tests/test_ensemble_dataset_benchmark.py` (new, 16 tests, `@unit`): tool logic, CLI, `sqlite3.connect` always restored, and
  a mutation check — a deliberately N+1 implementation is caught.
- `docs/ROADMAP.md`: N+1 item Planned -> Completed (refs §63 / `a702c27` and §77).
- `CLAUDE.md`: Current Priorities item 5 marked DONE (same style as items 1-2).
- `learning/application/recommendation_context.py`: `_find_contradictions` docstring no longer cites a nonexistent "documented
  N+1 ceiling"; points at §77. Docstring only.
- `docs/architecture.md` §77, `CHANGELOG.md`, this file, `MIGRATION.md`.

## Impact

None on runtime: no production module's executable code changed (one docstring), no settings, schema or dependency change.

## Gates

Run on the branch before commit (fresh-clone re-run from the bundle is recorded in PR_DESCRIPTION.md):

- `ruff check .` (and with `--exclude dashboard_src --exclude dashboard`): All checks passed.
- `vulture . --exclude dashboard_src,dashboard,tests`: `--min-confidence 80` empty on both `main` and branch (diff identical);
  `--min-confidence 60` 432 lines on both, identical ignoring line numbers.
- `python -c "import main"`: OK.
- `pytest tests/ -q`: **3409 passed, 3 failed, 4 skipped, 45 deselected**. Baseline `main` @ `ec67c57`: 3393 passed, 3 failed,
  4 skipped, 45 deselected. Delta = +16 (the new benchmark tests). The 3 failures are `tests/test_dashboard_serving.py`
  (need `dashboard_src/dist`; CI builds it first, which is why §76 recorded 3396 passed = 3393 + those 3; same environment
  effect, not caused by this PR).
- §76 regression tests (`tests/test_ceo_vote_persistence_lifecycle.py`) and §63's `tests/test_ensemble_dataset_bulk_fetch.py`
  pass UNCHANGED (neither file is modified in this diff).

## Limits / follow-up

Sandbox numbers (Python 3.12.3, SQLite 3.45.1), not the production VPS; synthetic data (3 symbols, 5 agent rows/trade); journal
read only (not the `learning/` pipeline above it). Not started, by instruction: agent-key namespace mismatch (§76 P1, behavioral)
and learning-dataset cohorts (§76 P2) — each gets its own brief.
