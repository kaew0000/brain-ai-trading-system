# PATCH NOTES — V16 Phase 4C Step 8: Persistent Trading Knowledge Layer (Track A)

Branch: `feature/phase4c-step8-persistent-trading-knowledge`
Base: `main` @ `4f6df7c` (verified current — origin/main had moved since
Step 7C via PR #51 + an unrelated PR #52 "W14 live start-stop control
plane"; both confirmed real and re-based against before this phase began)

## Scope note

No prior documentation defines a "Phase 4C Step 8" — checked
`docs/architecture.md`, `CLAUDE.md`, `docs/ROADMAP.md`, and the Google
Sheets project tracker before starting; all are frozen at or before
Phase 4C Step 1. This phase's scope was supplied directly by the
project owner as an explicit, detailed brief, not discovered in
existing docs or guessed.

## Summary

A git-versioned, persistent Markdown knowledge layer that accumulates
institutional memory from the trading system's own real data
(`journal_v2`, including Phase 4C Step 7C's signal_id attribution
bridge), following Andrej Karpathy's "LLM Wiki" architecture pattern
(adapted, not copied): immutable raw sources → a maintained,
cross-linked wiki → an append-only chronological log. Informational /
analytical only — cannot place trades, modify orders, or touch
risk/execution/lifecycle state (verified structurally, see Safety
section below).

## What changed (all new, nothing existing modified)

- `knowledge_engine/` — new package, 9 modules: `provenance.py`,
  `pages.py`, `raw_store.py`, `chronolog.py`, `contradiction.py`,
  `trade_knowledge.py`, `agent_knowledge.py`, `index_builder.py`,
  `source_pages.py`.
- `raw/` — new, empty (`.gitkeep` only) immutable-source staging tree:
  `research/`, `trade_reviews/`, `market_notes/`, `incidents/`,
  `architecture/`, `operator_notes/`, `external/`.
- `knowledge/` — new, empty (`.gitkeep` only) wiki tree: `trades/`,
  `agents/`, `sources/`. `index.md`/`log.md` are generated on first
  use, not pre-created.
- `tests/test_knowledge_*.py` — 10 new files, 77 tests.
- `docs/architecture.md` — new §36.

No existing file was modified. `journal/journal_v2.py` was not
touched — this package only calls its existing `get_*` readers.

## Why `knowledge/` and `raw/` ship empty

This phase ships the mechanism, proven against real `journal_v2`
objects in tests (real SQLite, real Step 7C signal_id joins — not
mocks). It does not seed the repository's actual `knowledge/`/`raw/`
directories with content, because the only trade/agent data available
in this environment is synthetic test fixtures — writing that into
the committed knowledge tree would be exactly the fabricated
production data the brief's Hard Rules and spec §14 prohibit. Real
ingestion against the real production journal is the operator's own
next action (see MIGRATION.md).

## Safety audit

`tests/test_knowledge_safety.py` — AST-based (not grep) static proof
that `knowledge_engine/`:
- imports nothing from `execution/`, `risk/`, `decision/`, `agents/`,
  `portfolio/`, `commander/`, `world/`, `dashboard*/`, or any
  Binance/exchange client;
- every local repository import is from `journal` or `knowledge_engine` itself;
- never calls any `journal_v2` method whose name starts with
  `save_`/`update_`/`delete_` — walks the AST for attribute access,
  not a text match;
- imports no networking library (`requests`/`httpx`/`websocket*`).

## Secret audit

`raw_store.ingest_raw_source()` refuses to stage content matching a
conservative secret-shaped pattern set (private key blocks, AWS-style
key ids, `BINANCE_API_KEY`/`BINANCE_API_SECRET` assignments, generic
`api_key=`/`password=`/`token=` assignments) — raises
`SecretDetectedError`, content is never written to disk in that case
(`tests/test_knowledge_raw_store.py::TestSecretDetection`). Manually
re-checked: no `.env`, credential, or token content exists anywhere in
this phase's diff.

## Test results

- `pytest tests/test_knowledge_*.py -q` → 77 passed
- Full `pytest tests/ -q` → see FINAL REPORT
- `pytest world/tests/ -q -m ""` → see FINAL REPORT (untouched, unrelated)
- `ruff check .` → clean
- `vulture . --min-confidence 80` → clean
- `python -c "import main"` → clean
- `git diff --check` → clean

## Known follow-up work (explicitly out of scope for this phase)

- Strategy and Regime entity pages (spec §5 lists them; no real
  synthesis logic exists for them yet — not fabricated with
  placeholders).
- Query/retrieval tooling beyond "read index → follow links" (spec
  §11 — no embeddings/vector DB; explicitly not needed yet).
- Wiring this package into `main.py`'s scheduler or any live process —
  there is no existing LLM/AI runtime interface anywhere in this
  codebase to wire it to (checked; none exists).
- Actually running a first real ingestion against the production
  journal — operator's own next action.
