# SECURITY_AUDIT.md — Brain Bot V13

**Audit Date:** 2026-06-19

---

## 🔴 CRITICAL — Keys in Version Control (FIXED)

**Finding:** `.env` contained live Binance API keys (mainnet + testnet) in plaintext.  
**Risk:** Any person with access to the distributed zip could:
- Extract market data using mainnet keys (limited impact — read-only endpoints)
- Place orders on the Binance Testnet (fake money, low impact)
- If deployed to mainnet: place real orders (HIGH risk)

**Fix Applied:**
1. All key values redacted from `.env` (set to empty strings)
2. `.gitignore` added with `.env*` coverage
3. Added `!.env.example` to keep template tracked

**Recommendation:** Rotate ALL exposed keys immediately, even testnet keys.

---

## ✅ No Secret Leakage in Logs

Checked all logger calls across 70 files:
- `BINANCE_API_KEY` / `BINANCE_API_SECRET` never appear in log messages ✅
- `settings` model uses Pydantic; secrets not exposed in `repr()` ✅
- FastAPI `/api/config` endpoint returns config without secrets ✅

```python
# api/app.py /api/config — verified clean
return _ok({
    "symbol":    settings.SYMBOL,
    "leverage":  settings.LEVERAGE,
    # ← No API keys here ✅
})
```

---

## ✅ XSS / Injection Prevention

| Vector | Status | Notes |
|--------|--------|-------|
| SQL Injection | ✅ Safe | Parameterised queries throughout `journal_v2.py` |
| XSS via API | ✅ Safe | JSON responses only; no HTML rendering of user input |
| CORS | ⚠️ Open | `allow_origins=["*"]` — acceptable for local dashboard |
| WebSocket auth | ⚠️ None | No token auth on WS endpoints — OK for localhost use |

---

## ✅ Safe File Access

- No `os.system()` or `subprocess` calls ✅
- File paths constructed from `__file__` (not user input) ✅
- SQLite database paths from `settings.DATABASE_PATH` (env var) ✅
- Dashboard static files served only from fixed `dashboard/` directory ✅

---

## ✅ SQLite Safety

- All queries use `?` parameterised placeholders ✅
- WAL mode enabled in `database/db.py` (concurrent read safety) ✅
- Transactions used for multi-row inserts ✅
- No raw string interpolation in SQL ✅

---

## ⚠️ CORS Open Policy

`allow_origins=["*"]` is acceptable for a local trading dashboard but would be a risk in production web deployment. If deployed on a VPS with a public IP, restrict to specific origins.

**Recommendation:** For VPS: `allow_origins=["http://localhost:8000", "http://YOUR_VPS_IP:8000"]`

---

## ⚠️ No WebSocket Authentication

WS endpoints (`/ws/events`, `/ws/signals`, `/ws/decision`) accept all connections. In local use this is fine. On a public VPS, add token-based auth.

**Recommendation:**
```python
@app.websocket("/ws/events")
async def ws_events(ws: WebSocket, token: str = Query(...)):
    if token != settings.API_TOKEN:
        await ws.close(code=1008)
        return
```

---

## ⚠️ Agent Chat Endpoint — No Rate Limiting

`POST /api/chat` calls the AI agent layer synchronously. No rate limiting means a malicious client could flood the endpoint. Since this runs locally, impact is low.

---

## Summary

| Category | Status |
|----------|--------|
| API Keys in VCS | 🔴 CRITICAL (FIXED) |
| Secret leakage in logs | ✅ Clean |
| SQL injection | ✅ Safe |
| XSS | ✅ Safe |
| File access | ✅ Safe |
| CORS | ⚠️ Open (local use OK) |
| WS auth | ⚠️ None (local use OK) |
| Rate limiting | ⚠️ None (local use OK) |
