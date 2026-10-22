# MIGRATION — Strategy Intelligence Bundle

## Do you need to do anything?

No. Nothing in Brain Bot imports the new package, there is no new dependency (PyYAML is imported lazily, only when a YAML
config file is loaded; it is already present transitively via `uvicorn[standard]`), no new `.env`/settings flag, no schema or
database change. Merge and deploy as usual; trading behaviour is unchanged.

## Trying it (optional, from the repo root)

1. `pytest tests/test_bsi_*.py -q` — 101 offline tests.
2. `python -m brain_strategy_intelligence demo` — end-to-end on SYNTHETIC data; output in `brain_strategy_intelligence_data/`
   (gitignored).
3. `python -m brain_strategy_intelligence init-kb` then `evaluate <id> --csv <your candles.csv> ...` for real-data evaluation.
   Edit a copy of `config/strategy_intelligence.yaml` first: fee/slippage/funding values are assumptions.

Optional extras (not needed for offline use): `storage.backend: postgres` (install `psycopg[binary]`, `pgvector`; env
`BSI_POSTGRES_DSN`); `llm.provider: anthropic` + `llm.model` + env `ANTHROPIC_API_KEY`.

## Wiring into Brain Bot (NOT done in this phase)

See `docs/strategy_intelligence/INTEGRATION.md` (file-by-file). Manual prerequisites: verify `RiskEngine` semantics for the
risk-context mapping, verify journal columns for the trade mapping, supply real candles, and never wire the output into
`CEOAgent.WEIGHTS` voting without governance approval.

## Rollback

`git revert` the single commit (or delete `brain_strategy_intelligence/`, `config/strategy_intelligence.yaml`,
`docs/strategy_intelligence/`, `tests/test_bsi_*.py`, `tests/_bsi_helpers.py`, and the one `.gitignore` line). Delete
`brain_strategy_intelligence_data/` to remove any local databases/reports. Nothing persisted outside that directory.
