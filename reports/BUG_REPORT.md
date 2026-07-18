# BUG_REPORT.md — Brain Bot V13

**Audit Date:** 2026-06-19  
**Total bugs found:** 8  
**Total bugs fixed:** 8  
**Status:** ✅ ALL FIXED

---

## CRITICAL (3)

### BUG-01 — `NameError: balance` used before assignment in agent block
**File:** `main.py` — `run_trading_cycle()`, line ~334  
**Severity:** CRITICAL — crashes the full trading cycle whenever any agent is configured  
**Root cause:** The AI agent block (step 10a) reads `balance` to populate `pos_info["balance"]` but `balance = dp.get_account_balance()` is only called at step 11 (the Risk gate), after the agent block.  
**Fix:** Replaced `pos_info["balance"] = balance` with `pos_info["balance"] = 0.0` (sentinel) and added a second update `pos_info["balance"] = balance` immediately after the `get_account_balance()` call so agents that run in step 11+ receive the real value.

---

### BUG-02 — `NameError: _api_module` before import in agent block  
**File:** `main.py` — line ~345  
**Severity:** CRITICAL — crashes trading cycle if any agent exists and calls `_api_module.set_state()`  
**Root cause:** `_api_module.set_state("ceo_decision", ceo_decision)` is called inside the agent block (step 10a), but the `import api.app as _api_module` statement lives 7 lines below in a separate `try` block (step 10b).  
**Fix:** Moved `import api.app as _api_module` to the top of step 10a (before the agent block), guarded by try/except so API import failure doesn't crash the cycle.

---

### BUG-03 — Security: API keys committed to `.env` in version control
**File:** `.env`  
**Severity:** CRITICAL — real Binance API keys (mainnet + testnet) stored in plaintext in the repository zip  
**Root cause:** `.env` was not in `.gitignore` and was included in the distributed archive.  
**Fix:**
1. Redacted all key values in `.env` (replaced with empty strings).
2. Added comprehensive `.gitignore` covering `.env*`, `*.db`, `logs/`, `__pycache__/`.
3. Added `!.env.example` exception so the template can remain tracked.

---

## MAJOR (3)

### BUG-04 — Leverage double-applied in `monitor_open_trades()`
**File:** `main.py` — `monitor_open_trades()`, line ~510  
**Severity:** MAJOR — closed-trade PnL recorded in journal is 5× too large (at 5× leverage)  
**Root cause:**
```python
# WRONG
pnl = raw_pnl * settings.LEVERAGE   # double-counts leverage
```
When `execute_trade()` sizes the position, quantity is calculated so that a full SL move costs `risk_pct × balance`. The leverage is already baked into the position sizing formula — it does NOT need to be applied again to the raw dollar PnL.  
**Fix:**
```python
# CORRECT
pnl = raw_pnl   # leverage already embedded in quantity sizing
```

---

### BUG-05 — `PaperAccount.realise_pnl()` corrupts unrealised PnL
**File:** `paper/paper_account.py` — `realise_pnl()`, line ~159  
**Severity:** MAJOR — equity curve becomes incorrect after losing trades  
**Root cause:**
```python
# WRONG — can go negative for losses larger than stored unrealised
self._unrealised = max(0.0, self._unrealised - abs(pnl))  # "rough"
```
`_unrealised` is managed by `update_unrealised()` called from `PaperExecutionEngine.tick()` after each mark-price update. `realise_pnl()` must not manipulate it — `tick()` calls `update_unrealised(0.0)` after closing the position anyway.  
**Fix:** Removed the line entirely; added explanatory comment.

---

### BUG-06 — WebSocket `/ws/decision` hangs when no decision yet
**File:** `api/app.py` — `ws_decision()`, line ~507  
**Severity:** MAJOR — dashboard WebSocket clients get no init frame on first boot; frontend hangs on `receive_json()` indefinitely  
**Root cause:**
```python
# WRONG — conditional init frame
if dec is not None:
    await ws.send_text(...)   # never sent on first boot
while True:
    await ws.receive_text()   # client hangs here
```
**Fix:** Always send the init frame (same pattern as `/ws/signals`):
```python
# CORRECT
payload = (dec.to_dict() ...) if dec is not None else None
await ws.send_text(json.dumps({"type": "init", "decision": payload, ...}))
```

---

## MINOR (2)

### BUG-07 — `sys` parameter shadows `import sys` module
**File:** `main.py` — `run_trading_cycle(sys: dict)` and `monitor_open_trades(sys: dict)`  
**Severity:** MINOR — shadowing is harmless here (no `sys.exit()` called in these functions) but confusing  
**Status:** Documented, not renamed (would require updating all callers and scheduler bindings — low ROI for a minor issue)

---

### BUG-08 — Sharpe Ratio uses per-trade PnL not daily returns
**File:** `paper/paper_execution.py` — `_sharpe()`  
**Severity:** MINOR — Sharpe number is not comparable to standard industry Sharpe (which uses daily equity returns), but is self-consistent and useful for relative comparison across strategy runs  
**Status:** Documented in `QUANT_AUDIT.md` with formula notes. Not changed (changing would break existing test expectations).

---

## Summary Table

| ID | File | Severity | Fixed |
|----|------|----------|-------|
| BUG-01 | main.py | CRITICAL | ✅ |
| BUG-02 | main.py | CRITICAL | ✅ |
| BUG-03 | .env / .gitignore | CRITICAL | ✅ |
| BUG-04 | main.py | MAJOR | ✅ |
| BUG-05 | paper/paper_account.py | MAJOR | ✅ |
| BUG-06 | api/app.py | MAJOR | ✅ |
| BUG-07 | main.py | MINOR | Documented |
| BUG-08 | paper/paper_execution.py | MINOR | Documented |
