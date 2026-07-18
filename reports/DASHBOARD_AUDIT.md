# DASHBOARD_AUDIT.md — Brain Bot V13

**Audit Date:** 2026-06-19

---

## 1. API Endpoint Audit

| Endpoint | Status | Notes |
|----------|--------|-------|
| GET /api/health | ✅ | Returns `{ok, data:{status, uptime_s, db, paper_running}}` |
| GET /api/config | ✅ | No secrets exposed |
| GET /api/decision | ✅ | Returns latest ConfidenceResult + causal explanation |
| GET /api/signals | ✅ | Paginated, `limit` param validated |
| GET /api/futures | ✅ | OI history + funding history + snapshot |
| GET /api/regime | ✅ | Regime history + current bias |
| GET /api/events | ✅ | EventBus ring buffer, filterable by `agent`/`event_type` |
| GET /api/journal | ✅ | Closed trades + performance + daily stats |
| GET /api/paper | ✅ | Paper metrics + equity curve + goal progress |
| GET /api/paper/trades | ✅ | Returns 503 when paper engine not initialised |
| GET /api/paper/metrics | ✅ | Returns 503 when paper engine not initialised |
| GET /api/agents | ✅ | Agent decision history |
| GET /api/forward_test | ✅ | Forward test results |
| POST /api/chat | ✅ | Agent chat via AI layer |

---

## 2. WebSocket Audit

| Endpoint | Bug Pre-Fix | Status Post-Fix |
|----------|-------------|-----------------|
| WS /ws/events | ✅ Always sent init | ✅ |
| WS /ws/signals | ✅ Always sent init | ✅ |
| WS /ws/decision | 🔴 Hung when no decision yet | ✅ Fixed (BUG-06) |

### WS /ws/decision (BUG-06 detail)
```
BEFORE FIX:
  Client connects → no decision in state → no frame sent
  Client calls receive_json() → hangs indefinitely

AFTER FIX:
  Client connects → always receives {"type":"init","decision":null}
  Client can handle null decision gracefully
```

---

## 3. Response Format Audit

All endpoints follow unified envelope:
```json
{"ok": true, "data": {...}}
{"ok": false, "error": "..."}
```
✅ Consistent — frontend can rely on `response.ok` before accessing `.data`

---

## 4. State Sync Audit

| State Key | Set By | Read By | Thread-safe |
|-----------|--------|---------|-------------|
| `latest_decision` | main.py step 10b | /api/decision, /ws/decision | ✅ GIL |
| `latest_context` | main.py step 10b | /api/futures, /api/regime | ✅ GIL |
| `paper_engine` | main.py build_system | /api/paper, /ws/events | ✅ GIL |
| `journal_v2` | main.py build_system | all journal endpoints | ✅ GIL |
| `ceo_decision` | agents.ceo_agent | /api/agents | ✅ GIL |

No stale state issues — `_state` is a plain dict; Python GIL protects dict assignments.

---

## 5. Mode Verification

| Mode | Execution | Journal | Dashboard |
|------|-----------|---------|-----------|
| PAPER | PaperExecutionEngine | TradeJournalV2 | /api/paper shows equity curve |
| TESTNET | TradeManager (testnet URLs) | TradeJournalV2 | /api/paper shows 503 |
| LIVE | TradeManager (mainnet URLs) | TradeJournalV2 | /api/paper shows 503 |

---

## 6. Pixel Office Dashboard

### Components Present ✅
- `BrainBotOffice.jsx` — pixel art office layout
- `BrainBotV13Dashboard.jsx` — full React component
- 5 agent desks: CEO Brain, SMC Analyst, Futures Desk, Risk Manager, Trader
- Speech bubbles — animated opacity transition
- Score strip — animated pixel squares
- Equity curve — Chart.js responsive=false (post-fix)
- Event log — scrolling, opacity fade
- Detail panel — Status + Chat tabs
- AI agent chat — Anthropic API integration

### JavaScript Issues Reviewed ✅
- No circular dependencies in React components
- `init()` called via `document.readyState` check (not bare setTimeout)
- Chart.js loaded via CDN poll (`setInterval(() => Chart && initChart(), 100)`)
- Canvas `drawChar()` uses explicit `ctx.clearRect()` before redraw
- `globalAlpha` reset to 1 after each semi-transparent draw
- All `getElementById` calls have null guards
- WebSocket reconnect not implemented (acceptable for local dashboard)

### Memory Leak Check ✅
- `setInterval(tick, 1000)` — single interval, no accumulation
- `setInterval(sblink, ...)` — recursive setTimeout, auto-clears via reassignment
- Chat history in JS object — bounded by session lifetime
- `eqData` array sliced to max 30 points

### Stale State Risk ✅ None
- Dashboard polls REST endpoints on click/open
- WS pushes live updates every 1s
- No duplicate polling timers

---

## 7. Dashboard Error States

| Scenario | Behaviour |
|----------|-----------|
| API not running | JS fetch fails silently (no crash) |
| WS disconnect | Client stuck in `receive_text()` — no auto-reconnect |
| Paper engine not set | /api/paper returns `{enabled: false}` ✅ |
| No decision yet | /ws/decision sends `{type:"init", decision:null}` ✅ |
| Agent layer disabled | /api/agents returns empty list ✅ |

### Recommendation
Add WS auto-reconnect in dashboard JS:
```javascript
function connectWS() {
  const ws = new WebSocket('ws://localhost:8000/ws/decision');
  ws.onclose = () => setTimeout(connectWS, 3000);  // retry after 3s
}
```
