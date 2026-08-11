# PATCH NOTES — V16 Phase 4C Step 7C: CEO → Agent → Trade Attribution Signal-ID Bridge (Track A)

Branch: `feature/phase4c-step7c-signal-id-bridge`
Base: `main` @ `df50be9` (2348 + 565 passing, ruff clean — verified via
fresh clone, not session context)
Track: A (backend/engine) only — no Track B (`world/`, `dashboard_src/`) files touched.

## Summary

Threads one shared `signal_id`, created once per CEO decision cycle,
through the full attribution chain: CEO_AGENT journal row → every
participating sub-agent's own journal row → the outgoing
`ExecutionSignal` → the trade row persisted at open time. This is what
makes `journal_v2.get_trade_attribution()`'s existing
`trades.signal_id == agent_decisions.signal_id` join actually populate
`agent_participation` for CEO-gated trades — before this phase it
always returned an (honestly) empty list, since neither side of that
join was ever written for this path.

## Prerequisite verification

A task brief for this phase initially claimed the implementation
already existed from a prior session (specific field names, a 16-test
file, "16/16 passing"). Independent verification against a fresh
`origin/main` clone found none of it — no such field on `ExecutionSignal`,
no such test file on any branch (local or remote), and Step 7's own
docstring (PR #48, real, merged) already documented this exact scope
as explicitly deferred future work. The brief's claim was fabricated;
the underlying gap it described was real and is what this phase closes.

## What changed

### `execution/execution_orchestrator.py`
- `ExecutionSignal` (frozen dataclass) gains `signal_id: int | None = None`
  — trailing, defaulted, backward compatible with every existing
  positional/keyword construction site.
- `_record_trade_opened()`: if the incoming signal already carries a
  `signal_id`, reuse it — never mint a second, unrelated one for the
  same trade. If not (every pre-Step-7C caller), behavior is
  byte-identical to before: mint a fresh signal row here.

### `execution/ceo_gated_signal_provider.py`
- `_journal_ceo_decision()` now:
  1. Creates exactly one `signal_id` per CEO decision cycle via
     `journal.save_signal()` (best-effort — degrades to `signal_id=None`
     on any failure, never raises).
  2. Passes it into the existing `CEO_AGENT` journal row.
  3. **New**: writes one additional, independently-inspectable
     `save_agent_decision()` row per real entry in
     `ceo_decision.agent_reports`, sharing the same `signal_id`. A
     single agent's write failure is logged and skipped, never blocking
     the rest.
  4. Returns the shared `signal_id`.
- `_get_signal_ceo_enabled()` threads that id onto the outgoing
  `ExecutionSignal` (via `dataclasses.replace()` — the dataclass is
  frozen) only when a trade was actually confirmed. A vetoed/WAIT/
  BLOCKED cycle still gets the full journal write (audit trail intact)
  but has nothing to attach the id to.

## Files changed

- `execution/execution_orchestrator.py` (modified)
- `execution/ceo_gated_signal_provider.py` (modified)
- `tests/test_ceo_multi_symbol_agent_attribution.py` (new — 17 tests)
- `tests/test_ceo_agent_vote_persistence.py` (1 assertion updated)
- `tests/test_recommendation_explanation_persistence.py` (1 assertion updated)
- `docs/architecture.md` (new §35 entry)
- `PATCH_NOTES.md`, `MIGRATION.md` (this phase's content)

## Test results

- Targeted: `tests/test_ceo_multi_symbol_agent_attribution.py` → 17 passed
- `tests/test_recommendation_explanation_persistence.py` → 14 passed
- Full `pytest tests/ -q` → 2365 passed, 0 failed (2348 baseline + 17 new)
- `pytest world/tests/ -q -m ""` → 565 passed, unchanged
- `ruff check .` → clean
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80` → clean
- `python -c "import main"` → clean
- `git diff --check` → clean

## Existing assertions changed (2, both explained)

`test_agent_reports_persist_to_journal_details` and
`test_live_decision_persists_explanations_to_journal` both asserted
`len(journal.saved) == 1` (CEO_AGENT row only). Both now assert
`1 + len(agent_reports)` — the real fixtures these tests already used
(a live 6-agent layer) always computed multiple agent votes; this
phase is what makes those votes get their own persisted rows instead
of being discarded after the CEO row's `details.agent_reports` blob
was written. No assertion was weakened — both still check every prior
invariant unchanged, plus the new row count.

## Performance impact

One additional lightweight `save_signal()` write and N additional
`save_agent_decision()` writes per CEO decision cycle (N = number of
real agents in that cycle's layer — 6 in production
(`agents/ceo_symbol_cache.py`'s `build_agent_layer()`)). No new query
plans, no schema change, no N+1 pattern introduced — each write is a
single-row `INSERT`, same shape every other `save_agent_decision()`
call in this codebase already makes.

## Known follow-up work (explicitly out of scope for this phase)

- Phase 4C Steps 3–7's own missing `docs/architecture.md` entries
  (pre-existing documentation drift, not introduced by this phase) —
  flagged in §35, not backfilled here.
- `CHANGELOG.md` / `docs/CHANGELOG.md` staleness — pre-existing,
  unrelated.
- The dashboard `/portfolio` mock-data issue — separate, unrelated,
  untouched (explicitly out of scope per this phase's own brief).
