# MIGRATION — AI Self-Improvement Governance Layer, Phase 1

## Do you need to do anything?

**No.** This phase changes zero existing behavior. It only adds a new,
empty database table, a new Python package (`governance/`), a new
agent (`agents/update_review_agent.py`), and 7 new config settings —
nothing pre-existing reads, calls, or is affected by any of it yet.
Import your bundle and restart exactly as normal.

## What's new, and why it's inert until Phase 2

- `update_proposals` (new table): starts empty. Nothing in this
  delivery writes a row to it — `ProposalStore.create()` exists and is
  fully tested, but no production code path calls it yet. That wiring
  (`ml/learning_mode.py`'s nightly retrain creating a proposal instead
  of calling `ModelRegistry.promote()` directly) is Phase 2, not this
  delivery. `run_nightly_retrain()` still auto-promotes exactly as it
  did before this phase — **unchanged**.
- `governance.proposal_store.ProposalStore` / `governance.
  update_proposal.UpdateProposal` / `agents.update_review_agent.
  UpdateReviewAgent`: all new, all importable, all covered by their
  own tests — but nothing else in the codebase imports them yet. They
  exist so Phase 2 has a tested foundation to build on, not because
  anything calls them today.
- Seven new `REVIEW_SCORE_*`/`REVIEW_MIN_SAMPLE_SIZE` settings in
  `config/settings.py`: only read by `agents/update_review_agent.py`,
  which nothing else calls yet. Safe defaults, but there is currently
  no way to reach them from a running bot.

## No default-behavior change (unlike the previous phase)

The previous phase (§47, training-lane visibility) flipped
`BACKGROUND_PAPER_TRAINING_ENABLED`'s default and needed an escape
hatch documented here. This phase makes **no** such change — every
new setting only affects code this same phase adds, and that code
isn't called from anywhere else yet. There is nothing to opt out of.

## Database

`update_proposals` is picked up automatically on next boot via the
normal `database/db.py::_apply_schema()` path — no separate migration
script to run, no manual step. Confirmed safe against a database file
that already has other V16 tables in it (that's exactly what
`CREATE TABLE IF NOT EXISTS` against the full schema script already
does for every other table in this file, e.g. `execution_events`).

## If you're reviewing the diff

Every new file is additive (`governance/*`, `agents/
update_review_agent.py`, three new `tests/test_*.py` files). The two
modified files (`config/settings.py`, `database/schema_v13.sql`) only
have insertions — no existing line was changed or removed in either.
