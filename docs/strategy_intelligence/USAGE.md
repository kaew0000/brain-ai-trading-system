# Usage (in-repo)

The package is `brain_strategy_intelligence/` at the repository root, run from the repo root with the project's existing Python
environment (3.12). **Tested only on Python 3.12.3 / Linux** (Windows is not verified). Importing it has no side effects and it needs
no new dependency (PyYAML is only imported lazily when a YAML config file is loaded).

```
# offline tests (no key, no network)
pytest tests/test_bsi_*.py -q

# CLI  (all output goes to ./brain_strategy_intelligence_data/, which is gitignored)
python -m brain_strategy_intelligence init-kb                   # loads the 9 example strategies
python -m brain_strategy_intelligence list
python -m brain_strategy_intelligence search "breakout channel" --regime TREND
python -m brain_strategy_intelligence evaluate trend-sma-cross --synthetic        # SYNTHETIC data, clearly labelled
python -m brain_strategy_intelligence evaluate trend-sma-cross --csv path\to\BTCUSDT_15m.csv --symbol BTCUSDT --timeframe 15m
python -m brain_strategy_intelligence rank --synthetic
python -m brain_strategy_intelligence research --snapshot snapshot.json
python -m brain_strategy_intelligence report
python -m brain_strategy_intelligence demo                      # end-to-end on SYNTHETIC data
python -m brain_strategy_intelligence --config config/strategy_intelligence.yaml list
```
Windows PowerShell: identical commands, e.g. `python -m brain_strategy_intelligence demo`.

Optional: PostgreSQL+pgvector (`pip install "psycopg[binary]>=3.1,<4" "pgvector>=0.2,<1"`, env `BSI_POSTGRES_DSN`,
`storage.backend: postgres` - **not executed in the build environment**); LLM provider (`llm.provider: anthropic`, `llm.model`,
env `ANTHROPIC_API_KEY`; without them everything runs offline); n8n (`brain_strategy_intelligence/workflows/`, **untested**).

## Disable / remove / roll back
- Disable: `BSI_ENABLED=false` (or `bundle.enabled: false`) - CLI becomes a no-op, the adapter returns `DISABLED` without touching storage.
- Remove: delete the `brain_strategy_intelligence/` directory, `config/strategy_intelligence.yaml`, `docs/strategy_intelligence/`, the
  `tests/test_bsi_*.py` + `tests/_bsi_helpers.py` files and the `.gitignore` line - or simply `git revert` the single commit.
- Nothing in existing Brain Bot code imports this package, so none of the above affects trading.
