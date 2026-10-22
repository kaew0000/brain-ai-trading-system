# Architecture

```
            +-------------------- brain_strategy_intelligence (standalone, research_only) --------------------+
 snapshot   |  integration/brain_bot_adapter  --recommend()-->  Recommendation (advisory, no order fields)    |
 (dict) --->|     |            |            |                                                                |
            |  knowledge/   research/    ranking/      evaluation/              learning/                    |
            |  repository   agent        ranker        evaluator                trade_recorder               |
            |  retrieval    providers    (weights)     backtester,engines       outcome_analyzer             |
            |  sqlite|pg    (opt. LLM)                 walk_forward,costs,data                               |
            |        \_____________ StrategyStore protocol (replaceable) _____________/                       |
            |  reporting/reports  -> JSON + Markdown (secret-redacted, atomic writes)      cli: python -m ...   |
            +---------------------------------------------------------------------------------------------+
```
Dependency direction (no cycles): `errors, security -> schemas, config -> interfaces -> knowledge, evaluation, learning, research -> ranking -> integration -> cli`.

## Modules
- **A Knowledge** - `StrategyDefinition` (versioned, provenance, `validation_status`). `SQLiteStrategyStore` (default; WAL, transactional, revision log) and `PgVectorStore` (optional, lazy import). Retrieval = 0.5 keyword + 0.3 hashed-embedding cosine + 0.2 declared-regime match. The embedder is lexical hashing, **not** a learned semantic model; swap via the `Embedder` protocol.
- **B Research** - `ResearchAgent` with `NullProvider` (offline rules), optional `AnthropicProvider` (stdlib HTTP, fixed host), or any callable. LLM output is parsed, schema-validated (strict), id-checked, and number-checked against the snapshot; failure falls back to offline rules.
- **C Evaluation** - six deterministic engines (`sma_cross, donchian_breakout, rsi_reversion, roc_momentum, bb_squeeze_breakout, mtf_confluence`), event-driven backtester (next-open fills, adverse slippage, fees, funding, stops with gap handling, exposure cap, long/short), chronological train/validation/OOS split, walk-forward with purge, parameter sensitivity. Insufficient data/trades -> `INCOMPLETE` with reasons.
- **D Ranking** - eight weighted components (config), INCOMPLETE never ranked, explainable `reasons`/`limitations`, deterministic tie-break.
- **E Learning** - idempotent SQLite recorder (closed + complete only; `verified` required for analysis), MFE/MAE, documented heuristic failure classification, per-strategy-version reports. Read-only: never edits strategies or logic.
- **F Adapter** - `snapshot_from_market_context`, `recommend()` (never raises; fail-closed statuses), `record_closed_trade()`.
- **G Reporting/automation** - JSON+Markdown reports, optional n8n workflow (`workflows/`).

## Validation lifecycle
`UNVALIDATED` (everything starts here) -> `BACKTESTED` (a COMPLETE evaluation exists; automatic) -> `VALIDATED` only via `KnowledgeRepository.mark_validated(...)` with a named approver, a COMPLETE non-synthetic evaluation of the same version. Revising a strategy creates a new version reset to `UNVALIDATED`. Ranking never changes status.

## Known simplifications
Single asset, one position, no order-book model, liquidation not modelled, constant funding assumption, "multi-timeframe" engine is a lookback-scaled proxy (not true resampling), regime stability is approximated by walk-forward window profitability.
