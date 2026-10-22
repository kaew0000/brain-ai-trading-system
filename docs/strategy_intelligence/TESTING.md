# Testing

```
ruff check .                       # repo config (ruff.toml)
vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80
pytest tests/test_bsi_*.py -q      # this feature only (all marked `unit`, so the repo's -m unit default selects them)
pytest tests/                      # full suite
```
All fixtures are SYNTHETIC (random-walk/hand-built candles, made-up trades) and labelled so (`tests/_bsi_helpers.py`).
Coverage map: persistence/versioning (`test_bsi_knowledge`), snapshot/record validation (`test_bsi_schemas`), backtest arithmetic, costs,
look-ahead, walk-forward separation, missing data (`test_bsi_evaluation`), ranking (`test_bsi_ranking`), duplicate/incomplete trades and
classification (`test_bsi_learning`), adapter/disabled/config isolation/no-execution surface (`test_bsi_integration`), invalid LLM output,
timeouts, injection, secrets, optional-dependency isolation, source safety scan (`test_bsi_failure_modes`), CLI (`test_bsi_cli`).

## NOT executed (and why)
PostgreSQL/pgvector backend (no server; only the unavailable-path is tested) - live Anthropic provider (no key/network by design) -
n8n workflow import (no instance) - Windows/PowerShell - Python versions other than 3.12.3 - real market data - integration against a
running Brain Bot. Statistical heuristics (degradation test, sensitivity thresholds, ranking weights) are not calibrated.
