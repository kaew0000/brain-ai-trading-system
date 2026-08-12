# MIGRATION — V16 Phase 4C Step 8: Persistent Trading Knowledge Layer (Track A)

## Do you need to do anything?

**No, not to keep the system running exactly as before.** This phase
adds a new, standalone package (`knowledge_engine/`) and two new,
currently-empty data directories (`raw/`, `knowledge/`). Nothing
existing was modified — no schema change, no config flag, no import
added to any file outside this phase's own new files. `main.py`, the
scheduler, the dashboard, and every trading/risk/execution path are
byte-for-byte unchanged.

## If you want to actually use it

The knowledge layer isn't wired into any scheduled job — you invoke it
yourself, e.g. from a Python shell or a small script, pointed at your
real journal:

```python
from journal.journal_v2 import TradeJournalV2
from knowledge_engine.trade_knowledge import ingest_closed_trade
from knowledge_engine.agent_knowledge import ingest_agent_performance
from knowledge_engine.index_builder import rebuild_index
from knowledge_engine.chronolog import append_log_entry

journal = TradeJournalV2()  # uses your real configured DB path

# One closed trade:
page = ingest_closed_trade(journal, trade_id=123)
if page:
    append_log_entry("ingest", f"trade-{page.entity_id}")

# All agents with attributed trades so far:
for page in ingest_agent_performance(journal):
    append_log_entry("update", f"agent-{page.entity_id}")

rebuild_index()  # regenerate knowledge/index.md from every page's frontmatter
```

Everything writes under `knowledge/` and `raw/` at the repository
root by default (both `Path` parameters, overridable per-call).

## What this can never do, even fully wired up

- Cannot place a trade, modify an order, change SL/TP, alter risk
  limits, override the CEO gate, or change execution mode —
  structurally impossible, not just policy: `knowledge_engine/` has no
  import path to any module that could do those things, and calls no
  `journal_v2` write method (verified by
  `tests/test_knowledge_safety.py`'s AST audit).
- Cannot fabricate a win rate from too little evidence — below 5
  attributed trades, an agent's page says `INSUFFICIENT_EVIDENCE`,
  never a number.
- Cannot silently lose a prior claim when new evidence disagrees —
  large swings are recorded as a `## Revision History` entry, not
  overwritten.
- Cannot stage a secret into the git-versioned `raw/` tree — content
  matching a secret-shaped pattern is refused, not silently dropped.

## Rollback

Delete `knowledge_engine/`, `raw/`, `knowledge/`, and
`tests/test_knowledge_*.py`. Nothing else references them — no import
anywhere outside this phase's own files, no config flag to unset, no
schema to reverse.
