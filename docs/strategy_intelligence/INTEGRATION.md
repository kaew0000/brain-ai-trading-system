# Integration guide (Brain Bot V16.5.0)

**State after this phase: nothing in Brain Bot imports `brain_strategy_intelligence`.** It is inert until you wire it, and every hook
below is optional, additive and observe-only. Evidence for each interface named is in `AUDIT.md`.

## Adapter contract
```python
from brain_strategy_intelligence.config import load_config
from brain_strategy_intelligence.integration.brain_bot_adapter import BrainBotAdapter, snapshot_from_market_context

adapter = BrainBotAdapter.from_config(load_config("config/strategy_intelligence.yaml"))
snap = snapshot_from_market_context(market_context, risk={"trading_allowed": True, "max_leverage": 1, "risk_pct": 0.01})
rec = adapter.recommend(snap)     # never raises; rec.advisory_only is True, rec.may_execute is False
```
Statuses: `OK, DISABLED, REJECTED_INVALID_SNAPSHOT, REJECTED_STALE_SNAPSHOT, REJECTED_MISSING_DATA, REJECTED_RISK_BLOCKED, ERROR`.
`Recommendation` has no order/size/price/leverage field. Snapshot JSON for `research --snapshot`:
`{"symbol":"BTCUSDT","timestamp":"...Z","mark_price":65000.0,"regime":"TREND","risk":{"trading_allowed":true,"max_leverage":1,"risk_pct":0.01}}`

## File-by-file
| Existing file | Changed in this phase? | If you later integrate |
|---|---|---|
| `.gitignore` | **yes** - one line: `brain_strategy_intelligence_data/` | - |
| `requirements.txt` | no | PyYAML is lazy; nothing to add |
| `config/settings.py` | no | Intentionally untouched: the package has its own validated config (`config/strategy_intelligence.yaml`) and no flag affects trading |
| `intelligence/market_context_builder.py` | no | **Read** its `build()` output and pass it to `snapshot_from_market_context` |
| `risk/risk_engine.py` | no | **Read** `RiskEngine` to build the `risk` dict. Observed: `get_risk_pct`, `get_leverage`, `check_daily_loss`, `has_manual_hold`; return semantics NOT verified - confirm before mapping `trading_allowed` |
| `journal/journal_v2.py`, `journal/trade_attribution.py` | no | Map closed-trade rows to `TradeRecord` and call `adapter.record_closed_trade`. Column names NOT verified. Set `verified=true` only after fee backfill/reconciliation |
| `decision/*`, `agents/ceo_agent.py` | no | Do **not** wire into voting. Per `CEOAgent.WEIGHTS`, new agents outside it are telemetry-only; vote-wiring needs governance approval (G5/G6) |
| `execution/*`, `execution/strategy_registry.py` | no | Never: the package registers no strategy and sends no order |
| `learning/` (read-only package) | no | Distinct package; no shared code or state |

## Manual steps required
1. Decide how/if to call the adapter (suggested: a new observe-only hook module wrapped in try/except, logging the `Recommendation`).
2. Put real fee/slippage/funding assumptions in your copy of `config/strategy_intelligence.yaml`.
3. Provide real candles (CSV export or a `DataAdapter`); results on SYNTHETIC data can never validate a strategy.
4. Verify `RiskEngine` semantics, then implement the risk-context mapping.
5. Verify journal columns, then implement the journal -> `TradeRecord` mapping.
6. Review strategies yourself and call `KnowledgeRepository.mark_validated(..., approved_by=<you>)`; nothing does it automatically.
