# PERFORMANCE_AUDIT.md — Brain Bot V13

**Audit Date:** 2026-06-19

---

## 1. Trading Loop Performance

| Operation | Estimated Time | Bottleneck? |
|-----------|---------------|-------------|
| 3× OHLCV fetch (500 bars each) | 1.5–3s | Network I/O |
| SMC MTF analysis | 200–500ms | CPU (pandas) |
| RegimeEngine (HMM fit first time) | 500ms–2s | CPU (sklearn) |
| RegimeEngine (subsequent calls) | 100–300ms | CPU (HMM score) |
| VolumeEngine | 50ms | CPU |
| ConfidenceEngine | 5ms | Negligible |
| CausalExplainer | 2ms | Negligible |
| Agent layer (7 agents) | 20–50ms | Negligible |
| DB writes (journal) | 10–30ms | SQLite I/O |
| **Total (typical)** | **2–5s** | Network-bound |

**Loop interval:** 60 seconds → ample headroom ✅

---

## 2. CPU Profile

### Hotspots (profiled mentally from code analysis):

**RegimeEngine.classify():**
- Calls `self._scaler.fit_transform()` every cycle (refits scaler)
- **Fix:** Cache scaler between cycles; only refit every N cycles or on cold start

```python
# Recommendation:
if not self._fitted or self._cycle_count % 50 == 0:
    X_scaled = self._scaler.fit_transform(X_raw)
    self._cached_X_scaled = X_scaled
else:
    X_scaled = self._scaler.transform(X_raw)
```

**SMCEngine:** pandas operations on 500-bar DataFrames — acceptable.

---

## 3. Memory Usage

| Component | Memory |
|-----------|--------|
| 3 OHLCV DataFrames (500 bars) | ~3 MB |
| HMM model | <1 MB |
| EventBus ring buffer (1000 events) | <5 MB |
| SQLite WAL file | Variable |
| **Estimated total** | **~50 MB** |

No memory leaks detected:
- `_ws_events._clients` uses `set` + `discard` (stale clients removed) ✅
- `paper_account._equity_curve` grows unbounded (one entry per trade) — negligible for 200-trade target ✅

---

## 4. SQLite Performance

- WAL mode: concurrent reads from API while trading writes ✅
- Indexes on `timestamp` and `symbol` columns ✅
- `get_signals(limit=50)` → single indexed scan ✅
- `get_performance_summary()` → aggregation on `result` column (no index) ⚠️

**Recommendation:** Add `CREATE INDEX idx_trades_result ON trades(result)` for faster win/loss counts at 10k+ trades.

---

## 5. WebSocket / API Performance

- `_broadcast_loop()` polls every 1 second (not push) — acceptable for 60s trading cycles ✅
- Fan-out to N clients is O(N) — fine for local/small team use ✅
- No blocking operations in async handlers ✅

---

## 6. Thread Safety

| Resource | Protection | Status |
|----------|-----------|--------|
| `_state` dict (api.app) | None (GIL only) | ✅ OK (dict assignments atomic under GIL) |
| `PaperAccount` | `threading.Lock()` | ✅ |
| `PaperExecutionEngine` | `threading.Lock()` | ✅ |
| `EventBus` | `threading.Lock()` | ✅ |
| `SQLite` (journal_v2) | Per-connection WAL | ✅ |

---

## 7. Recommendations (Priority Order)

1. **Cache sklearn StandardScaler** between RegimeEngine cycles (saves 100–300ms/cycle)
2. **Add DB index** on `trades.result` for performance > 10k trades
3. **Batch journal writes** — currently 4 separate inserts per cycle (signals + regime + funding + OI); consolidate into a single transaction
4. **WebSocket push** — replace 1s polling in `_broadcast_loop` with EventBus callback for true push (currently no meaningful issue at 60s cycle time)
