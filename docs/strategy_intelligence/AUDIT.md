# Phase 1 audit (performed 2026-10-22)

Method: shallow clones (`--depth 1`) of both repositories into a scratch directory; read-only inspection by directory listing, `grep`,
and reading selected files. Nothing in either repository was modified. **Brain Bot's own test suite was not run** and its git history was
not inspected (shallow clone).

## Brain Bot (`kaew0000/brain-ai-trading-system`, HEAD `9bffc44`, "Merge pull request #110 ...smc-m5-gating")
| Item | Finding (evidence) |
|---|---|
| Version | `README.md` line 1: "Brain Bot V16.5.0" |
| Python | `README.md`: "Python 3.12+". `setup.bat` message says 3.10+ (inconsistent; this bundle requires 3.12) |
| Packaging | No `pyproject.toml`/`setup.py`; flat top-level packages (`agents`, `risk`, `ranking`, `research`, `learning`, `knowledge_engine`, ...) |
| Dependencies | `requirements.txt`: pydantic>=2, pandas, numpy, scipy, scikit-learn, SQLAlchemy, fastapi, httpx, binance-futures-connector ... **PyYAML is not listed (it is present transitively via `uvicorn[standard]`)** (imported lazily by the bundle, only when a YAML config file is loaded, so `requirements.txt` is unchanged) |
| Lint config | `ruff.toml`, line-length 120 (bundle matches) |
| LLM infrastructure | `grep -rIl -E "anthropic\|openai\|ollama\|llm" --include=*.py` (excluding tests) returned **no files** -> no LLM client exists to reuse; the bundle ships its own optional provider |
| Backtester | No strategy backtester module found. The word "backtest" appears in `ml/extensions/hpo/manager.py`, `ml/extensions/orchestrator.py`, `ml/extensions/example.py`, `execution/order_timeline.py`; **those files were not read in depth** |
| Existing overlap | `research/` (feature vectors/datasets), `ranking/` (opportunity ranker), `learning/` (read-only observation), `knowledge_engine/`, `forward_test/`, `training_lane/`, `execution/strategy_registry.py` (StrategySpec/register_strategy). The bundle uses its own namespace `brain_strategy_intelligence` so it cannot shadow any of these |
| Market snapshot schema | `intelligence/market_context_builder.py` docstring: `symbol, timestamp, mark_price, regime (TREND/RANGE/VOLATILE/SQUEEZE), regime_conf, trend_bias, trend_strength, futures_signal, fear_greed, macro_risk, futures{...}` - mapped in `snapshot_from_market_context`. `research/trade_snapshot.py` reads `futures.funding.rate` and `futures.open_interest.value` |
| Risk Manager | `risk/risk_engine.py` `RiskEngine`: `get_risk_pct(balance, atr_pct)`, `get_leverage(atr_pct)`, `check_daily_loss(balance)`, `check_consecutive_losses()`, `has_manual_hold()`. Signatures observed; **return semantics not verified**. Market context contains no risk data |
| Decision/CEO | `decision/brain_decision_engine.py` (`BrainDecisionEngine`, `DecisionResult`); `agents/ceo_agent.py` has a static `WEIGHTS` dict (per project rules, agents not in it are telemetry-only) |
| Journal | `journal/journal_v2.py` has trade-close recording (`trade_id`, `exit_price`, `pnl`), `journal/trade_attribution.py` accepts `fees`. **Exact table columns were not verified** -> trade mapping is a documented manual step |
| Candle history | No stable public candle-history interface verified -> `DataAdapter` protocol + CSV adapter instead |

## ORSTAC (`alanvito1/ORSTAC`)
- License: **MIT**, (c) 2025 Alan Victor.
- Content: README, `ai-catalog.json`, `index.html`, `Bots_XML/` (33 files in the checkout), `champions/` (3 XML bots + text notes), `docs/`, and `orstac-agent/` (docker-compose, `init-db.sql`, `.env.example`, `knowledge/*.md|json`, three n8n workflow JSONs: `01_ingest_resources`, `02_cognitive_brain`, `03_learning_loop`).
- `find . -name "*.py"` -> **0 Python files**; no JS/TS sources. The "bots" are Deriv Blockly XML for a different platform (binary options).
- **Reusable as architecture inspiration only**: (1) a searchable strategy knowledge base, (2) an ingest -> reason -> learn loop, (3) optional n8n scheduling over PostgreSQL. No code, XML bot, or data was copied. Deriv-specific logic is irrelevant to Binance Futures.
- Not inspected in depth: the n8n workflow node graphs and `init-db.sql` schema.

## Assumptions and missing interfaces (documented, not invented)
1. Strategy rules run only through the bundle's built-in deterministic engines; Brain Bot's SMC/volume/derivatives engines are not callable from here, so those three example strategies are *knowledge-only* and evaluate as INCOMPLETE.
2. Risk context, trade-journal mapping and candle history must be supplied by the integrator (docs/INTEGRATION.md).
3. Cost parameters (fees, slippage, funding) are configured assumptions, not measured values.
