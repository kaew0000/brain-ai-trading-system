# V14_PHASE2_5_TELEMETRY.md — Brain AI Trading Command Office

**Phase:** 2.5 — Institutional-grade telemetry infrastructure (backend only, no frontend)
**Date:** 2026-06-21
**Status:** Complete — 682/682 tests passing (453 v13 baseline + 229 new)

---

## Architecture Update

```
┌──────────────────────────────────────────────────────────────────────────────┐
│              BRAIN AI TRADING COMMAND OFFICE v14 — Phase 2.5                 │
└──────────────────────────────────────────────────────────────────────────────┘

main.py (orchestrator)
  │
  ├─ build_system() registers 1 new singleton:
  │    mission_tracker  (shared with api.app via the import-time singleton)
  │
  ├─ run_trading_cycle()
  │    [NEW] Commander pause check          — skips cycle if paused
  │    [EXISTING] steps 1–10 unchanged
  │    [NEW] Mission: SIGNAL_FOUND → VALIDATION   (after confidence scoring)
  │    [EXISTING] step 11 risk gate
  │    [NEW] Mission: RISK_CHECK  (pass) | CLOSED (blocked, abort)
  │    [NEW] Commander paper-mode-forced safety check
  │    [NEW] Mission: CLOSED (skipped — safety override)
  │    [EXISTING] step 12 execute
  │    [NEW] Mission: EXECUTION (success) | CLOSED (failed, abort)
  │    [NEW] Mission: EXECUTION → MONITORING   (next cycle, position confirmed open)
  │
  ├─ monitor_open_trades()
  │    [EXISTING] position close detection
  │    [NEW] Mission: MONITORING → CLOSED   (pnl/result attached to meta)
  │
  └─ agents/* (BaseAgent.run(), CEOAgent.decide())
       [EXISTING from Phase 2] TelemetryRegistry.record()
       [NEW] ReasoningStream.record()   — thought/reasoning/decision/confidence

api/app.py (FastAPI dashboard)
  │
  ├─ [EXISTING] 14 REST + 3 WS endpoints (v13)
  ├─ [Phase 2]  GET /api/agents/telemetry, WS /ws/agents
  └─ [Phase 2.5, NEW]
       GET  /api/agents/reasoning      — ReasoningStream
       GET  /api/agents/graph          — agent dependency graph (React Flow shape)
       GET  /api/intelligence          — funding/OI/liquidations/fear_greed/econ_calendar
       GET  /api/missions              — mission list (filterable)
       GET  /api/missions/{id}         — mission detail + full history
       WS   /ws/missions               — active missions, push ~1Hz
       GET  /api/command/state         — current pause/paper_mode_forced flags
       POST /api/command               — execute a Commander command
       WS   /ws/command                — bidirectional command execution
```

---

## New Modules

| Module | Responsibility |
|--------|----------------|
| `telemetry/agent_telemetry.py` | (Phase 2) status/confidence/latency/uptime per agent |
| `reasoning/reasoning_stream.py` | thought/reasoning/decision narrative per agent run |
| `graph/agent_graph.py` | CEO + 6-agent dependency tree, React Flow node/edge format |
| `intelligence/market_intelligence_service.py` | unified funding/OI/liquidations/fear_greed/econ_calendar |
| `missions/mission_tracker.py` | 6-stage lifecycle state machine for trade ideas |
| `commander/control_state.py` | global pause / paper-mode-forced flags |
| `commander/commander_service.py` | natural-language command parser + executor |

All seven are pure-stdlib, thread-safe, process-wide singletons with `reset_*()` test hooks — consistent with the existing `events/event_bus.py` pattern.

---

## Agent Dependency Map (updated)

```
agents/__init__.py: build_agent_layer(risk_engine, journal)
  │
  ├── SMCAnalyst / FuturesAnalyst / RegimeAnalyst / RiskManagerAgent /
  │   TraderAgent / JournalAnalyst
  │       │  BaseAgent.run() now records BOTH:
  │       │    1. TelemetryRegistry  (status/latency/confidence)
  │       │    2. ReasoningStream    (thought/reasoning/decision)  ← NEW
  │       └─→ via _thought_text()/_reasoning_text() helpers, built
  │           from AgentReport.summary and AgentReport.factors
  │
  └── CEOAgent.decide()
        records its own telemetry AND reasoning entries (doesn't go
        through .run(), so wired separately, same pattern as Phase 2)
```

---

## API Contracts

### `GET /api/agents/reasoning`

Query params: `limit` (default 50), `agent` (filter), `latest_only` (bool)

```json
// GET /api/agents/reasoning?latest_only=true
{
  "ok": true,
  "data": {
    "reasoning": {
      "SMC_ANALYST": {
        "agent": "SMC_ANALYST",
        "thought": "Bullish BOS on M15, confidence rising",
        "reasoning": "BOS: Bullish (Bullish structure break); FVG: 67200 (unmitigated gap supports LONG)",
        "decision": "LONG",
        "confidence": 82.0,
        "timestamp": "2026-06-21T07:40:17.123Z"
      }
    },
    "agent_count": 1,
    "timestamp": "2026-06-21T07:40:18.001Z"
  }
}
```

### `GET /api/agents/graph`

No params. Returns React Flow node/edge shape — see `graph/agent_graph.py` docstring for full schema. `source` is `"live"` when the bot is running with an active agent layer, `"static"` otherwise (dashboard never sees an empty canvas).

### `GET /api/intelligence`

Query params: `refresh_fear_greed` (bool, bypasses 10-min cache)

```json
{
  "ok": true,
  "data": {
    "funding":           {"rate": 0.0001, "annualised": 10.0, "extreme": false, "bias": "LONG_PAYING"},
    "open_interest":     {"delta_pct": 0.012, "trend": "RISING", "pressure": "BULLISH"},
    "liquidations":      {"detected": false, "type": "", "severity": "LOW"},
    "fear_greed":        {"value": 63, "classification": "Greed", "timestamp": "...", "available": true},
    "economic_calendar": {"events": [], "available": false},
    "timestamp": "2026-06-21T07:40:18.001Z"
  }
}
```

### `GET /api/missions` / `GET /api/missions/{id}`

Query params (list): `stage`, `limit` (default 50), `active_only` (bool)

```json
// GET /api/missions/{id}
{
  "ok": true,
  "data": {
    "id": "a1b2c3d4e5f6",
    "symbol": "BTCUSDT",
    "direction": "LONG",
    "stage": "CLOSED",
    "confidence": 78.0,
    "created_at": "2026-06-21T07:40:17.000Z",
    "updated_at": "2026-06-21T08:12:03.000Z",
    "history": [
      {"stage": "SIGNAL_FOUND", "timestamp": "...", "note": "Signal discovered"},
      {"stage": "VALIDATION",   "timestamp": "...", "note": "Agent layer + confidence scoring complete"},
      {"stage": "RISK_CHECK",   "timestamp": "...", "note": "Risk gate passed"},
      {"stage": "EXECUTION",    "timestamp": "...", "note": "Order filled"},
      {"stage": "MONITORING",   "timestamp": "...", "note": "Position confirmed open on exchange"},
      {"stage": "CLOSED",       "timestamp": "...", "note": "WIN pnl=42.50 U"}
    ],
    "meta": {
      "entry_price": 67000.0, "stop_loss": 65800.0, "take_profit": 69400.0,
      "regime": "TREND", "quantity": 0.1, "pnl": 42.50,
      "exit_price": 69412.0, "result": "WIN"
    }
  }
}
```

### `POST /api/command`

```json
// Request
{"command": "pause trader"}

// Response
{
  "ok": true,
  "data": {
    "command": "pause trader",
    "matched": "pause_trader",
    "success": true,
    "message": "Trader paused. No new trades will be opened until resumed.",
    "data": {"paused": true},
    "timestamp": "2026-06-21T07:40:18.001Z"
  }
}
```

Supported commands (token-based matching, case-insensitive, extra words OK):

| Command | Effect |
|---------|--------|
| `pause trader` | Sets `paused=true` — `run_trading_cycle()` skips entirely on the next scheduled call |
| `resume trader` | Clears `paused` |
| `paper mode on` | Sets `paper_mode_forced=true` — real order placement skipped regardless of `EXECUTION_MODE` (safety override, NOT a full engine hot-swap — see honesty note below) |
| `paper mode off` | Clears the override — `EXECUTION_MODE` governs again |
| `show positions` | Reads live open positions (paper engine or exchange) |
| `show pnl` | Reads paper metrics or journal performance summary |
| `show risk` | Reads `RiskEngine.report(balance)` |

**Honesty note on "paper mode on/off":** `EXECUTION_MODE` is fixed at process startup. Hot-swapping the live `TradeManager` instance at runtime (full engine replacement) is out of scope for this phase — it would require position reconciliation and credential re-validation, too risky to bolt on safely. What "paper mode on" actually does: sets a flag that `run_trading_cycle()` checks immediately before calling the real execution engine; if set, real order placement is skipped entirely and the mission is closed with a clear note. This is an honest emergency brake, not a silent no-op and not an overclaimed full hot-swap.

### `GET /api/command/state`

```json
{"ok": true, "data": {"paused": false, "paper_mode_forced": null, "updated_at": "..."}}
```

---

## WebSocket Contracts

### `WS /ws/agents` *(Phase 2)*
Push-only, ~1Hz. Init frame always sent (empty `{}` if no agents have run yet).
```json
{"type": "telemetry", "data": {"SMC_ANALYST": {...}, ...}, "timestamp": "..."}
```

### `WS /ws/missions`
Push-only, ~1Hz, active (non-CLOSED) missions only. Init frame always sent (empty `[]` if none).
```json
{"type": "missions", "data": [{...mission...}], "timestamp": "..."}
```

### `WS /ws/command` *(bidirectional)*
Client sends either a JSON object `{"command": "show positions"}` or a bare string `"show positions"`. Server executes via the same `CommanderService` used by the REST endpoint and replies with exactly **one** `command_result` frame, fanned out to every connected client (multi-tab sync) — not duplicated to the sender.

```
→ client sends:  {"command": "pause trader"}
← server broadcasts to ALL connected /ws/command clients:
   {"type": "command_result", "data": {CommandResult...}}
```

Init frame on connect: `{"type": "init", "data": {ControlSnapshot...}, "timestamp": "..."}`

---

## Event Flow Map (updated)

```
Trading cycle (main.py, every 60s)
  │
  ├─ [NEW] Commander pause check — early-return if paused
  │
  ├─ ConfidenceEngine.score() → ConfidenceResult
  │
  ├─ ceo.decide(ctx, confidence_result)
  │    ├─ 6× sub-agent.run(ctx) → AgentReport
  │    │    → TelemetryRegistry.record()      [Phase 2]
  │    │    → ReasoningStream.record()         [Phase 2.5, NEW]
  │    │    → EventBus.publish()
  │    └─ CEODecision
  │         → TelemetryRegistry.record() (CEO_AGENT)
  │         → ReasoningStream.record() (CEO_AGENT)              [NEW]
  │
  ├─ [NEW] if action ∈ {LONG,SHORT}:
  │      MissionTracker.create()         → SIGNAL_FOUND
  │      MissionTracker.advance()        → VALIDATION
  │
  ├─ Risk gate
  │    [NEW] ok  → MissionTracker.advance() → RISK_CHECK
  │    [NEW] !ok → MissionTracker.advance() → CLOSED (abort)
  │
  ├─ [NEW] Commander paper_mode_forced check
  │      forced → MissionTracker.advance() → CLOSED (skip execution)
  │
  ├─ TradeManager.execute_trade()
  │    [NEW] success → MissionTracker.advance() → EXECUTION
  │    [NEW] !success → MissionTracker.advance() → CLOSED (abort)
  │
  └─ [next cycle] position confirmed open
       [NEW] MissionTracker.advance() → MONITORING

monitor_open_trades() (every 30s)
  └─ position closes (TP/SL/manual)
       [NEW] MissionTracker.advance() → CLOSED (pnl/result in meta)

api.app._broadcast_loop() [1Hz background task]
  ├─ [EXISTING] /ws/events, /ws/signals, /ws/decision
  ├─ [Phase 2]  TelemetryRegistry.snapshot() → /ws/agents
  └─ [Phase 2.5, NEW] MissionTracker.get_active() → /ws/missions
```

---

## Test Coverage Summary

| Subsystem | Test file | Tests |
|-----------|-----------|-------|
| Agent Reasoning Stream | `test_reasoning_stream.py` | 33 |
| Agent Relationship Graph | `test_agent_graph.py` | 25 |
| Market Intelligence Feed | `test_market_intelligence.py` | 25 |
| Mission Pipeline (standalone) | `test_mission_tracker.py` | 38 |
| Mission Pipeline (main.py integration) | `test_mission_pipeline_integration.py` | 16 |
| Commander Interface | `test_commander.py` | 55 |
| **Phase 2.5 total** | | **192** |
| Phase 2 (Telemetry, prior) | `test_telemetry.py` | 37 |
| v13 baseline | (9 files) | 453 |
| **Grand total** | | **682** |

All main.py wiring (mission lifecycle transitions, Commander pause check, paper-mode-forced safety override) is covered by genuine integration tests that call the real `run_trading_cycle()` / `monitor_open_trades()` functions with mocked dependencies — not just "imports without crashing". Two real bugs were caught and fixed during this build:

1. **`telemetry_timer` latency_ms=0.0 on error path** (Phase 2 self-review) — fixed by making `latency_ms` a live property instead of a frozen `__exit__`-only value.
2. **`/ws/command` duplicate reply** — `ConnectionManager.broadcast()` already includes the sender (added via `connect()`), so a separate direct `ws.send_text()` reply was sending every command result twice. Fixed by relying solely on the broadcast; caught by a dedicated regression test (`test_ws_command_no_duplicate_reply`).

---

## Defensive Wiring Guarantees

Every new main.py touchpoint (mission lifecycle calls, Commander pause/paper-mode checks) is wrapped in `try/except` with debug-level logging on failure — consistent with the established pattern from the v13 BUG-01/02 fixes. This is verified by `TestDefensiveContract` in `test_mission_pipeline_integration.py`: even if the mission tracker raises mid-cycle, `run_trading_cycle()` still completes and `trade_manager.execute_trade()` still gets called. Telemetry/reasoning/mission infrastructure can never block real trading.
