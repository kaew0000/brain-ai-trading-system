# V14_PHASE1_AUDIT.md — Brain AI Trading Command Office

**Audit Date:** 2026-06-20
**Scope:** Full repository audit before v14 upgrade (Pixel Agents HQ / Bloomberg Terminal-class dashboard)
**Baseline:** brain_bot_v13_audited (453/453 tests green, 71 Python files)

---

## Architecture Map

```
┌──────────────────────────────────────────────────────────────────────────┐
│                  BRAIN AI TRADING COMMAND OFFICE v14                     │
└──────────────────────────────────────────────────────────────────────────┘

  main.py (orchestrator, unchanged)
    │
    ├─→ [EXISTING] Data → Feature → Regime → Intelligence → Decision layers
    │
    ├─→ [EXISTING] EventBus ──────────────┐
    │                                     │
    ├─→ [EXISTING] Agent Layer (7 agents) │
    │     CEO, SMC, Futures, Regime,      │
    │     Risk, Trader, Journal           │
    │         │                           │
    │         ▼                           │
    │   [NEW v14] TelemetryRegistry ◄──────┘
    │     (status/confidence/latency/
    │      uptime per agent)
    │         │
    │         ▼
    ├─→ api/app.py (FastAPI)
    │     [EXISTING] 14 REST + 3 WS endpoints
    │     [NEW v14]  GET /api/agents/telemetry
    │     [NEW v14]  WS  /ws/agents
    │
    └─→ [NEW v14] dashboard-v14/ (React + Tailwind SPA)
          9 pages: Overview, Agent Floor, Debate Room,
          Market Intelligence, Mission Board, Portfolio Center,
          Trade Replay, Journal Intelligence, Settings
```

---

## Agent Dependency Map

```
agents/__init__.py: build_agent_layer(risk_engine, journal)
  │
  ├── SMCAnalyst       (AGENT_NAME="SMC_ANALYST")      ─┐
  ├── FuturesAnalyst   (AGENT_NAME="FUTURES_ANALYST")   │  each calls
  ├── RegimeAnalyst    (AGENT_NAME="REGIME_ANALYST")    │  BaseAgent.run()
  ├── RiskManagerAgent (AGENT_NAME="RISK_MANAGER")      │  → telemetry
  ├── TraderAgent      (AGENT_NAME="TRADER_AGENT")      │  recorded
  ├── JournalAnalyst   (AGENT_NAME="JOURNAL_ANALYST")  ─┘
  │
  └── CEOAgent (AGENT_NAME="CEO_AGENT")
        │ holds references to all 6 above
        │ .decide(market_context, confidence_result)
        │   1. loop: agent.run(ctx) for each sub-agent  → 6x telemetry records
        │   2. weighted aggregation (WEIGHTS dict)
        │   3. risk veto check
        │   4. final action (LONG/SHORT/WAIT)
        │   5. [NEW v14] CEO's own telemetry record
        └─→ CEODecision (to_dict, npc_speech)
```

**Invocation site:** `main.py` step 10a — `ceo.decide(pos_info, confidence_result=decision)` (NOT via `.run()`)

---

## API Map

| Method | Path | Added In | Reads From |
|--------|------|----------|-----------|
| GET | /api/health | v13 | _state, _journal() |
| GET | /api/config | v13 | settings |
| GET | /api/decision | v13 | _state["latest_decision"] |
| GET | /api/signals | v13 | TradeJournalV2 |
| GET | /api/futures | v13 | _state["latest_context"] |
| GET | /api/regime | v13 | TradeJournalV2 |
| GET | /api/events | v13 | EventBus |
| GET | /api/journal | v13 | TradeJournalV2 |
| GET | /api/paper | v13 | _state["paper_engine"] |
| GET | /api/paper/trades | v13 | _state["paper_engine"] |
| GET | /api/paper/metrics | v13 | _state["paper_engine"] |
| GET | /api/agents | v13 | _state["agent_layer"] |
| **GET** | **/api/agents/telemetry** | **v14** | **TelemetryRegistry** |
| GET | /api/agents/{name} | v13 | _state["agent_layer"] |
| GET | /api/agents/{name}/memory | v13 | agent.get_memory() |
| POST | /api/chat | v13 | _state["agent_layer"] |
| GET | /api/forward_test | v13 | ForwardTestEvaluator |
| WS | /ws/events | v13 | EventBus (1Hz poll) |
| WS | /ws/signals | v13 | EventBus (1Hz poll) |
| WS | /ws/decision | v13 | _state["latest_decision"] |
| **WS** | **/ws/agents** | **v14** | **TelemetryRegistry (1Hz poll)** |

All new endpoints follow the existing `{ok, data}` envelope and the BUG-06 "always send init frame" pattern.

---

## Database Map (unchanged — v14 adds zero new tables)

```
journal_v2.db (SQLite, WAL mode)
  signals            — every decision cycle
  market_regimes     — regime classification history
  trades             — closed trade records
  funding_history    — funding rate snapshots
  oi_history          — open interest snapshots
  agent_decisions     — structured agent decision log
  agent_messages       — EventBus persisted events
  config_profiles       — saved weight/param presets
  ... (12 tables total, unchanged from v13)
```

Agent telemetry is **intentionally NOT persisted to SQLite** — it's a live, in-memory-only "current state" view (matches the spec's emphasis on real-time status, not historical telemetry). Historical agent behaviour is already captured via `agent_decisions` / `agent_messages` tables.

---

## Event Flow Map (v14 additions in bold)

```
Trading cycle (main.py, every 60s)
  │
  ├─ ConfidenceEngine.score() → ConfidenceResult
  │
  ├─ ceo.decide(ctx, confidence_result)
  │    ├─ smc.run(ctx)     → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    ├─ futures.run(ctx) → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    ├─ regime.run(ctx)  → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    ├─ risk.run(ctx)    → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    ├─ trader.run(ctx)  → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    ├─ journal.run(ctx) → AgentReport → EventBus.publish() → **TelemetryRegistry.record()**
  │    └─ CEODecision      → conf_pub.info/debug()            → **TelemetryRegistry.record()** (CEO_AGENT)
  │
  └─ api.app._broadcast_loop() [1Hz background task]
       ├─ EventBus.get_recent() → /ws/events, /ws/signals
       ├─ _state["latest_decision"] → /ws/decision
       └─ **TelemetryRegistry.snapshot() → /ws/agents**
```

---

## Risk Assessment for v14 Changes

| Change | Risk | Mitigation |
|--------|------|-----------|
| BaseAgent.run() wrapped with try/timing | LOW | Original exception re-raised unchanged; existing CEOAgent error handling untouched. Verified by `test_run_error_path_records_error_status_and_reraises`. |
| CEOAgent.decide() timing added | NONE | Purely additive — no control flow changed, only a `record()` call appended before `return dec`. |
| New api/app.py imports | NONE | telemetry module has zero dependencies on existing API internals. |
| New WS endpoint | NONE | Isolated `ConnectionManager` instance; doesn't touch existing `_ws_events/_ws_signals/_ws_decision`. |
| Broadcast loop extended | LOW | New branch only executes `if _ws_agents.count > 0` — zero overhead when no v14 dashboard client is connected. |

**Verdict: All Phase 1 + Phase 2 changes are additive and non-breaking.** 490/490 tests passing (453 baseline + 37 new).
