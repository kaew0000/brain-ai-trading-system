# CONFLICT_REPORT

Every file that differed between `Brain_Bot_RUN` and the merge base
(`p2_opportunity_ranker`) was checked with an AST-level comparison of
top-level functions and class methods (not line diffing) to catch
silent method/function loss. Results below.

## 1. The one item that needed manual verification

**`agents/risk_manager.py` — `RiskManagerAgent._calc_risk_pct` method
is absent in the patch version.**

Investigated by tracing the call site and the surrounding diff:

- In RUN, `RiskManagerAgent` computed the dynamic risk percentage
  itself, locally, from the consecutive-loss count.
- In the patch, that computation has moved into `RiskEngine`
  (`risk/risk_engine.py`), which gained two new methods in this same
  patch: `get_leverage` and `_volatility_factor`. `RiskManagerAgent`
  now reads `report["dynamic_risk_pct"]` from the engine's output
  instead of computing it inline.

**Resolution: not a regression.** This is the P1-B1 "dynamic risk"
patch's actual purpose — centralizing risk-percentage calculation in
`RiskEngine` so it can account for volatility (the new
`VOLATILITY_RISK_THRESHOLD` / `VOLATILITY_RISK_FLOOR` settings),
not just consecutive losses. The patch version was kept as-is.

## 2. Everything else: pure additions, no losses

AST comparison of the other 17 differing files found **zero removed
top-level functions or class methods** — every difference was a new
function, new method, or new class:

| File | Change |
|---|---|
| `api/app.py` | + `auth_token`, `auth_rotate`, `_auth_middleware`, `_payload_hash` (P1-A dashboard auth) |
| `config/settings.py` | + `Settings.symbol_list` property, new auth/scanner/ranker settings fields |
| `execution/trade_manager.py` | + `_is_duplicate_order_error`, `new_client_order_id` |
| `main.py` | + `_fetch_resting_sl_tp` |
| `risk/risk_engine.py` | + `_volatility_factor`, `get_leverage` |
| `system_health/watchdog.py` | + `WatchdogSupervisor` class (7 methods), `start_watchdog_supervisor` |
| `execution/execution_factory.py`, `system_health/reconciliation.py`, `utils/retry.py` | no def/method-level changes (formatting/comment/logic-only changes inside existing functions) |
| `database/schema_v13.sql` | + `scanner_snapshots`, `ranking_history` tables (additive DDL, `CREATE TABLE IF NOT EXISTS`) |
| `deployment/systemd/brain_bot.service` | `Type=simple` → `Type=notify` + `WatchdogSec=30`, matching the new `WatchdogSupervisor` (documented inline in the service file's own comments) |
| `requirements.txt` | + `PyJWT>=2.6.0` (needed by the new dashboard auth) |
| test files (10) | additive: new/expanded test cases only |

No file required a manual three-way merge. No conflicting resolution
was necessary beyond the one item in §1.

## 3. Config/secrets check

`config/settings.py` changes were reviewed specifically for anything
that could silently drop an environment-specific value: all new fields
are `Field(default=...)` with safe off-by-default values
(`API_AUTH_ENABLED=False`, `SCANNER_ENABLED=False`, etc.) read from env
vars/aliases at runtime — no hardcoded values were removed or
overwritten. Actual secrets live in `.env`, which was not touched by
any patch and was not copied into this repo (see
`GITHUB_READY_CHECKLIST.md`).
