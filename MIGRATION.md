# MIGRATION — V16 Phase 4B Step 1: Per-Agent Outcome Attribution

## Do you need to do anything?

**No config changes, no schema changes, no database migration.** This
phase reuses columns that already existed in `database/schema_v13.sql`
(`agent_decisions.signal_id`, `trades.signal_id`) — it just populates them
for the first time and adds one new read method. Existing databases work
as-is; new `agent_decisions`/`trades` rows going forward will simply have
their `signal_id` populated where they weren't before.

## Behavior change to be aware of

- `main.py`'s live pipeline now calls `journal.save_agent_decision(...)`
  once per sub-agent, per decision cycle (previously this method had zero
  call sites in production). If you have dashboard/API code that reads
  `/api` endpoints backed by `get_agent_decisions()`, you will start
  seeing real rows there instead of an empty table.
- `trades.signal_id` and `agent_decisions.signal_id` are now populated for
  trades taken through the **legacy single-symbol `main.py` pipeline**.
  They remain unpopulated (`NULL`) for anything else, including any
  historical trades saved before this phase.
- New method: `TradeJournalV2.get_agent_performance(limit=500)` → list of
  `{agent, total_trades, wins, losses, win_rate, total_pnl}`, one row per
  agent that has at least one closed (`WIN`/`LOSS`), direction-matching
  trade. An agent that only ever dissented from what was actually traded
  will not appear at all — that's intentional, not a bug.

## Important scope limitation

`get_agent_performance()` only reflects trades opened through the legacy
single-symbol pipeline in `main.py`. Positions opened/closed through
`execution/execution_orchestrator.py` (V16's multi-symbol path) are
**not** visible to it yet — that module doesn't write to the journal at
all today (confirmed by inspection: no `save_trade`/`update_trade_result`
calls anywhere in `execution/` or `portfolio/`). If your deployment
trades primarily through the multi-symbol path, `get_agent_performance()`
will currently return sparse or empty data. Closing that gap is scoped as
a separate, later phase — see `docs/architecture.md §27` "Next up".

## What's next (Phase 4B proper, not in this phase)

`get_agent_performance()` exposes raw per-agent win/loss data; it does
not yet change `CEOAgent.WEIGHTS`. A follow-up phase decides the actual
update rule (e.g. blend toward measured win-rate only once an agent has
some minimum number of closed trades, static weight below that floor)
and where it reads from — see `docs/architecture.md §27` "Next up".
