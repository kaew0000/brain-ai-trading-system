# MIGRATION — V16 Phase 4C Step 7C: CEO → Agent → Trade Attribution Signal-ID Bridge (Track A)

## Do you need to do anything?

**No.** Everything in this phase is additive and reuses existing,
already-optional columns. If you do nothing, the system behaves
exactly as it did before this phase, with one improvement:

- `ExecutionSignal.signal_id` defaults to `None` — every existing
  caller that constructs `ExecutionSignal(...)` without it is
  unaffected.
- `ExecutionOrchestrator._record_trade_opened()` only changes behavior
  when the incoming signal already carries a `signal_id` (i.e. it came
  through the CEO-gated path, after this phase). Every other caller —
  the plain `PortfolioSignalProvider` path, `execution/strategy_registry.py`
  — mints a fresh signal row exactly as before.
- `CEOGatedSignalProvider._journal_ceo_decision()`'s new per-agent
  journal rows are pure additions — nothing that previously read
  `journal.get_agent_decisions()` filtered by `agent="CEO_AGENT"` (the
  only row that previously existed) breaks; it now also sees N more
  rows it can choose to read or ignore.
- `journal_v2.get_trade_attribution()` is unchanged code — it already
  had this join built in (Phase 4B Step 2, §29). This phase is what
  starts actually populating both sides of that join for CEO-gated
  trades; the method itself required no change.

## What this enables

Once a CEO-gated trade is opened, `GET` its trade attribution (via
whatever endpoint already calls `journal_v2.get_trade_attribution(trade_id)`)
now returns a real, non-empty `agent_participation` list: one entry per
agent that voted that cycle (including `CEO_AGENT` itself, since it is
also a row sharing that cycle's `signal_id`), each with
`agent`/`vote`/`weight`/`confidence`/`contribution`. Before this phase,
that list was always empty for every CEO-gated trade, not because no
agents voted, but because neither side of the join was ever written.

## What this can never do, even fully enabled

- Does not change what the CEO decides, which agents exist, or how
  they're weighted — this is attribution/observability plumbing only.
- Does not backfill `signal_id` on trades opened before this phase —
  those rows keep whatever `signal_id` (real or `NULL`) they already
  had; `get_trade_attribution()` on them behaves exactly as before
  (empty `agent_participation` if it was empty before).
- Does not touch the plain (non-CEO) `portfolio_signal_provider.py`
  path's attribution — that path still has no agent layer to attribute
  to, unchanged (documented pre-existing scope boundary, §29).

## Rollback

Revert the two production files
(`execution/execution_orchestrator.py`,
`execution/ceo_gated_signal_provider.py`). No schema migration, no
data migration, no config flag to unset — every new column this phase
writes to already existed and defaulted to `NULL` before this phase;
reverting the code simply stops populating it going forward. Already-
written rows with a populated `signal_id` are harmless if left in
place (an old trade with a real join simply keeps working; nothing
reads `signal_id` as evidence that this phase's code is active).
