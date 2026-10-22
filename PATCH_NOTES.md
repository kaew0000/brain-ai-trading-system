# PATCH NOTES — Strategy Intelligence Bundle (research-only)

Branch: `feature/phase-strategy-intelligence`
Base: `main` @ `9bffc44` (Merge pull request #110, SMC M5 gating)
Commit: `feat(strategy-intelligence): Strategy Intelligence Bundle (research-only)` (exactly one)

## Root cause (why this phase exists)

Brain Bot has no way to store/search strategy knowledge, no strategy backtester, no LLM client, and no
cost-aware, out-of-sample ranking of candidate strategies (read-only audit on a fresh clone of `main`:
`grep -rIl -E "anthropic|openai|ollama|llm" --include=*.py` outside tests returned nothing; "backtest" appears only in
`ml/extensions/*` and `execution/order_timeline.py`; `ranking/` ranks *symbols/opportunities*, `learning/` is read-only
observation of live trades). Evidence in `docs/strategy_intelligence/AUDIT.md`. The reference project (ORSTAC, MIT) contains
no Python — only Deriv XML bots and an n8n/PostgreSQL agent — so only its *concepts* were adapted; no code was copied.

## Changes (all additive — no existing code path imports the new package)

New package `brain_strategy_intelligence/` (self-contained, namespace cannot shadow `ranking/`, `research/`, `learning/`):
- `knowledge/` — versioned strategy store (SQLite default, optional PostgreSQL+pgvector, lazy import), hybrid retrieval,
  validation policy (everything starts UNVALIDATED; revising resets status; only `mark_validated` with approver + COMPLETE
  non-synthetic evaluation can validate).
- `research/` — provider-independent agent: offline rules by default, optional LLM adapter; strict output validation,
  invented-number guard, bounded retries/timeouts, fallback to offline.
- `evaluation/` — 6 deterministic engines (no code execution), next-open-fill backtester with fees/slippage/funding/stops,
  train/validation/OOS split, walk-forward with purge, parameter sensitivity; INCOMPLETE instead of invented numbers.
- `ranking/` — 8 weighted, explainable components; INCOMPLETE never ranked.
- `learning/` — idempotent trade-outcome recorder (closed + complete + verified only), MFE/MAE, heuristic failure classes, reports.
- `integration/brain_bot_adapter.py` — advisory `Recommendation` (no order fields, `may_execute: Literal[False]`), fail-closed.
- `reporting/`, `cli.py`, `__main__.py` (`python -m brain_strategy_intelligence ...`), `strategies/` (9 examples, no performance
  claims), `workflows/` (optional n8n, untested).
- `config/strategy_intelligence.yaml` — mirrors code defaults (a test enforces equality). `bundle.mode` accepts only `research_only`.
- `tests/test_bsi_*.py` (8 files, 101 tests, all `@unit`) + `tests/_bsi_helpers.py`. `docs/strategy_intelligence/*` + `docs/architecture.md` §73.
- `.gitignore`: + `brain_strategy_intelligence_data/` (runtime DBs/reports).
- Untouched on purpose: `config/settings.py`, `requirements.txt` (PyYAML imported lazily), `main.py`, risk/decision/execution/agents.

## Impact

Zero runtime impact on trading: nothing imports the package; no new dependency; no settings flag; no schema change; no network
host other than an optional, off-by-default `api.anthropic.com` call.

## Quality gates (actually executed on this branch)

- `ruff check .` — All checks passed
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80` — clean (it caught `self_inner` in a first draft; refactored)
- `python -c "import main"` — OK
- `pytest tests/` — **3357 passed, 3 failed, 4 skipped, 45 deselected**. Baseline on unmodified `main` @ `9bffc44`:
  3256 passed, same 3 failed, 4 skipped, 45 deselected. Delta = +101 = this phase's tests. The 3 failures are
  `tests/test_dashboard_serving.py` (need `dashboard_src/dist`, which CI builds first) — pre-existing, unrelated.

## Limitations / known follow-up

- Verified only on Python 3.12.3 / Linux. NOT executed: PostgreSQL/pgvector backend, live Anthropic provider, n8n import, Windows.
- All test and demo data is SYNTHETIC; nothing here says anything about real-market profitability.
- 3 example strategies (SMC, support/resistance, volume/OI) are knowledge-only (no engine) and evaluate INCOMPLETE.
- "Multi-timeframe" engine is a lookback-scaled proxy; regime stability is approximated by walk-forward window profitability;
  statistical heuristics are uncalibrated; liquidation and order-book depth are not modelled; fee/slippage/funding are assumptions.
- Integration is deliberately NOT wired: risk-context mapping (RiskEngine return semantics unverified), journal -> TradeRecord
  mapping (columns unverified) and a candle-history DataAdapter are follow-ups (see `docs/strategy_intelligence/INTEGRATION.md`).
