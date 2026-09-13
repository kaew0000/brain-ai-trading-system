# PATCH NOTES — Fix N+1 Query in Ensemble Learning Dataset (V16 §63)

Branch: `perf/ensemble-dataset-n-plus-one`
Base: `main` @ `e22be6a` (merge of PR #98, multi-symbol reconciliation)

## Root cause

`journal/journal_v2.py::get_ensemble_learning_dataset()` called
`get_trade_attribution(trade_id)` once per matching trade — 2 queries
per trade (one for the trade row, one for its `agent_decisions`), on
top of the 1 query to list matching trade IDs. ~1+2N queries total.
Measured: ~0.079s for 2,000 trades under the fix below; the pre-fix
N+1 pattern was previously measured at ~28.5s for 10,000 trades — the
same O(N) shape, roughly 700x slower at that count purely from
per-row round-trip overhead, not data volume.

This was a **deliberate, documented** design choice, not an oversight
— the pre-existing docstring explained why: reusing
`get_trade_attribution()` per row meant the single-row and bulk-dataset
methods could never silently produce different shapes for the same
trade, at the cost of query count. That correctness goal is preserved
by this fix — see below.

## Fix

Extracted the row-shaping logic (previously the back half of
`get_trade_attribution()`, after its two queries) into a new
`@staticmethod _shape_trade_attribution(trade_d, agents)` — pure
data-in, dict-out, no queries. Both methods now share it:

- `get_trade_attribution(trade_id)` — unchanged query pattern (2
  queries per call), now calls the shared shaping helper at the end.
- `get_ensemble_learning_dataset(limit, symbol)` — rewritten to fetch
  in bulk instead of row-by-row: one query for every matching `trades`
  row, one query for every matching `agent_decisions` row (`WHERE
  signal_id IN (...)`), grouped in Python by `signal_id`, then each row
  shaped through the exact same helper. **2 queries total, regardless
  of `limit`.**

The row shape still lives in exactly one place
(`_shape_trade_attribution`), so the two methods' output cannot
silently drift apart from each other — the original design's whole
reason for reusing `get_trade_attribution()` per row is fully
preserved; only *how* the underlying data gets fetched changed.

Confirmed byte-for-byte behavioral equivalence (not just "should be
the same" — actually asserted dict equality row-for-row) across every
shape variation `get_trade_attribution()` handles: no `signal_id`,
`signal_id` with zero `agent_decisions` rows, several agents, an
explicit `agent_attribution` override, and the `symbol` filter.

## Tests

New: `tests/test_ensemble_dataset_bulk_fetch.py` — 9 tests.
- Query-count: compares total SQL statements traced (via
  `sqlite3.Connection.set_trace_callback`, since `sqlite3.Connection`
  is a C/immutable type its methods can't be monkeypatched directly)
  between 3 trades and 30 trades — must be identical (proving O(1),
  not O(N)); confirms `get_trade_attribution()`'s own per-call cost is
  unaffected by how many *other* trades exist.
- Output equivalence: `get_ensemble_learning_dataset()`'s row for a
  trade == `get_trade_attribution(trade_id)`'s output for that same
  trade, across every shape variation listed above.
- Regression guards for existing behavior: empty dataset, open trades
  excluded.

All 143 pre-existing tests across every file touching either method
(`test_agent_performance_attribution.py`, `test_ceo_agent_vote_
persistence.py`, `test_ceo_live_recommendation_wiring.py`,
`test_ceo_multi_symbol_agent_attribution.py`,
`test_execution_attribution.py` — which already had a dedicated
`get_ensemble_learning_dataset` test class covering empty/open-trades-
excluded/one-row-per-trade/symbol-filter/no-agent-participation —
`test_knowledge_trade.py`, `test_learning_dataset_builder.py`,
`test_learning_report.py`, `test_recommendation_dataset_row_count_
wiring.py`) pass unchanged.

Full suite: `pytest tests/` → **3105 passed** (up from 3096), 4
skipped, 45 deselected. Same 3 pre-existing
`tests/test_dashboard_serving.py` failures as every phase this week
(missing frontend build artifact) — unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on the changed file.
`python -c "import main"` → succeeds.

## Incidental fix (found while working in this area)

`docs/architecture.md`: the §61/§62 and several earlier section
boundaries (§57–§60) had a missing blank line — in §62's case,
literally no newline at all (`...succeeds.## 62. Multi-Symbol
Reconciliation...` on one line), from a previous phase's `cat >>` onto
a file that didn't end with a trailing blank line. §62's instance
would have prevented that heading from rendering as a heading at all
in strict Markdown. Fixed all instances found (a plain
missing-blank-line formatting pass, no content changes) while in this
file to add §63.

## Files changed

`journal/journal_v2.py`,
`tests/test_ensemble_dataset_bulk_fetch.py` (new), `docs/architecture.md`
(§63 + the incidental seam-formatting fix above), `PATCH_NOTES.md`,
`MIGRATION.md`, `CHANGELOG.md`.
