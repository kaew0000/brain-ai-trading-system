# SYSTEM_AUDIT.md — Brain Bot V13

**Audit Date:** 2026-06-19  
**Auditor:** Principal Quant Engineer / Senior Python Architect / Senior DevOps / Senior QA  
**Codebase:** 70 Python files · 13 layers · ~12,000 LOC

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         BRAIN BOT V13 — SYSTEM MAP                          │
└─────────────────────────────────────────────────────────────────────────────┘

  ┌──────────────┐
  │  main.py     │  ← Entry point · schedule · signal handlers · bootstrap
  │  (Orchestrator)│
  └──────┬───────┘
         │
         ▼
  ┌─────────────────────────────────────────────────────────────────────────┐
  │                          LAYER 1: DATA                                   │
  │  BinanceDataProvider                                                     │
  │  · Dual-client (market=MAINNET, trade=TESTNET)                          │
  │  · Clock-drift correction (sign_request patch)                          │
  │  · OHLCV H4/H1/M15 · Mark Price · OI · Funding · L/S · Taker          │
  └────────────────────────────┬────────────────────────────────────────────┘
                               │
         ┌─────────────────────┼──────────────────────┐
         ▼                     ▼                      ▼
  ┌─────────────┐    ┌───────────────────┐   ┌──────────────────┐
  │  LAYER 2    │    │    LAYER 3        │   │    LAYER 4       │
  │  SMCEngine  │    │  RegimeEngine     │   │  VolumeEngine    │
  │  (MTF: H4/  │    │  (HMM + rules     │   │  (spike/OBV/     │
  │  H1/M15)    │    │  TREND/RANGE/VOL) │   │  divergence)     │
  └──────┬──────┘    └────────┬──────────┘   └────────┬─────────┘
         │                    │                        │
         └─────────────┬──────┘──────────────┬─────────┘
                       ▼                     ▼
              ┌────────────────────────────────────────┐
              │        LAYER 5: INTELLIGENCE             │
              │  MarketContextBuilder                    │
              │  · TrendEngine (ADX / EMA H4)           │
              │  · FuturesIntelEngine (OI/fund/L/S)     │
              │  → unified market_context dict           │
              └────────────────────┬───────────────────┘
                                   │
                    ┌──────────────┴──────────────┐
                    ▼                             ▼
           ┌─────────────────┐        ┌─────────────────────┐
           │   LAYER 6       │        │     LAYER 7          │
           │ ConfidenceEngine│        │  CausalExplainer     │
           │ (0-100% score)  │        │  (structured JSON    │
           │ → ConfidenceRes │        │   reasoning)         │
           └────────┬────────┘        └──────────┬──────────┘
                    │                            │
                    └──────────────┬─────────────┘
                                   ▼
                          ┌────────────────┐
                          │   LAYER 8      │
                          │   EventBus     │
                          │  (pub/sub)     │
                          └──────┬─────────┘
                                 │
              ┌──────────────────┼──────────────────┐
              ▼                  ▼                  ▼
     ┌──────────────┐  ┌──────────────┐  ┌─────────────────┐
     │  LAYER 9     │  │  LAYER 10    │  │   LAYER 11      │
     │  RiskEngine  │  │ TradeManager │  │  AI Agent Layer │
     │  (daily loss │  │ (Binance API │  │  CEO/SMC/Risk/  │
     │  consec loss)│  │  execution)  │  │  Trader/Journal │
     └──────┬───────┘  └──────┬───────┘  └────────┬────────┘
            │                 │                    │
            └────────┬────────┘                   │
                     ▼                            ▼
            ┌─────────────────┐         ┌──────────────────┐
            │   LAYER 12      │         │    LAYER 13       │
            │ TradeJournalV2  │         │   Dashboard API   │
            │ (SQLite persist)│         │   FastAPI +WS     │
            └─────────────────┘         └──────────────────┘
```

---

## Dependency Graph

```
main.py
├── config.settings (Settings / EXECUTION_MODE)
├── data.binance_provider (BinanceDataProvider)
│   ├── binance.um_futures (UMFutures)
│   ├── data.validation
│   └── utils.retry
├── features.smc_engine (SMCEngine)
│   └── smartmoneyconcepts.smc
├── features.volume_engine (VolumeEngine)
├── regime.regime_engine (RegimeEngine)
│   ├── ta (ADX, BB, ATR)
│   ├── hmmlearn.hmm
│   └── sklearn.preprocessing
├── intelligence.market_context_builder (MarketContextBuilder)
│   ├── trend.trend_engine (TrendEngine)
│   └── futures.futures_intel_engine (FuturesIntelEngine)
├── decision.confidence_engine (ConfidenceEngine, ConfidenceResult)
├── decision.causal_explainer (CausalExplainer)
├── events.event_bus (EventBus, AgentPublisher)
├── execution.execution_factory (build_execution_engine)
│   ├── execution.trade_manager (TradeManager) [testnet/live]
│   └── paper.paper_execution (PaperExecutionEngine) [paper]
│       ├── paper.paper_account (PaperAccount)
│       └── paper.paper_position (PaperPosition)
├── analytics.trade_journal (TradeJournal, TradeRecord)  [legacy v1]
├── journal.journal_v2 (TradeJournalV2)                  [v2 — dashboard]
│   └── database.db
├── risk.risk_engine (RiskEngine)
├── agents (build_agent_layer → CEO + 6 employees)
│   ├── agents.ceo_agent
│   ├── agents.smc_analyst
│   ├── agents.futures_analyst
│   ├── agents.regime_analyst
│   ├── agents.risk_manager
│   ├── agents.trader_agent
│   └── agents.journal_analyst
├── forward_test.evaluator (ForwardTestEvaluator)
└── api.app (FastAPI dashboard)
    ├── GET /api/health|config|decision|signals|futures
    ├── GET /api/regime|events|journal|paper
    ├── GET /api/agents|forward_test
    ├── POST /api/chat
    └── WS  /ws/events|signals|decision
```

---

## Runtime Flow Graph

```
main() → build_system() → _start_api_server() → _open_browser()
  │
  └→ schedule every 60s: run_trading_cycle()
  └→ schedule every 30s: monitor_open_trades()
  └→ schedule every 1h:  daily_report()
  └→ run immediately on startup

run_trading_cycle():
  1. Position check (skip if open)
  2. Journal guard (skip if stale open)
  3. get_all_market_data()
  4. RegimeEngine.classify(H1)
  5. SMCEngine.analyze_mtf({H4,H1,M15})
  6. VolumeEngine.analyze(M15)
  7. MarketContextBuilder.build()
     → TrendEngine.analyse(H4)
     → FuturesIntelEngine.analyse(market_data)
  8. _derive_levels(direction, mark, ctx)
  9. ConfidenceEngine.score(ctx)
 10. CausalExplainer.explain(decision)
 10a. EventBus publish
 10b. Agent layer (CEO decides)
 10c. API state update
 10d. Journal persist (signal/regime/funding/OI)
 11. Balance fetch
 12. RiskEngine.can_trade()
 13. TradeManager.execute_trade()  [or PaperExecutionEngine.execute()]
 14. TradeJournalV2.save_trade()
```

---

## Module Interaction Map

| From | To | Via |
|------|-----|-----|
| main.py | BinanceDataProvider | direct call |
| main.py | ConfidenceEngine | direct call |
| main.py | EventBus | `brain_pub`, `conf_pub`, `risk_pub`, `regime_pub` |
| main.py | api.app | `set_state()` thread-safe write |
| api.app | TradeJournalV2 | `_journal()` injected instance |
| api.app | EventBus | `get_event_bus()` singleton |
| api.app | PaperExecutionEngine | `_state["paper_engine"]` |
| RiskEngine | TradeJournalV2 | `get_today_pnl()`, `get_consecutive_losses()` |
| AgentLayer | EventBus | `AgentPublisher` per agent |
| CEOAgent | All sub-agents | `agent.analyse(ctx)` |

---

## Data Flow Map

```
Binance API (MAINNET)
  └→ OHLCV, OI, Funding, L/S, Mark Price
       └→ market_context dict
            └→ ConfidenceResult
                 └→ EventBus (TRADE_DECISION)
                 └→ api._state (realtime)
                 └→ TradeJournalV2 (SQLite: signals, regimes, funding, oi)
                 └→ TradeManager → Binance TESTNET
                      └→ TradeJournalV2.save_trade()
                           └→ /api/journal, /api/paper, /api/signals
```

---

## Statistics

| Metric | Value |
|--------|-------|
| Total Python files | 70 |
| Approximate LOC | ~12,000 |
| Test files | 9 |
| Test count (pre-audit) | 393 |
| Test count (post-audit) | 453 |
| Database tables | 12 |
| API endpoints (REST) | 14 |
| API endpoints (WS) | 3 |
| Agent types | 7 (CEO + 6) |
| Execution modes | 3 (paper/testnet/live) |
