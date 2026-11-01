# V16 §96 — Trading-path bug audit & hand-off

Date: 2026-11-01 · Branch: `fix/failed-trade-phantom-loss-s96` · Base: `main` @ `45fc675` (PR #136 merged) · Next PR number: **#137**
Audited by: Claude (read of the real code from a full clone + pytest). Scope and limits are stated honestly in §4.

## 1. TL;DR for the next agent
The symptom "trading is incomplete / the bot stops trading" has one confirmed root cause (BUG-S96-01): **an order that fails is journaled as `OPEN`; the monitor then
settles it as a phantom `LOSS`; three of those trip the consecutive-loss risk gate with zero real losses.** Fixed here (with tests that fail on the old code).
Everything else found is listed in §3 as **open** with file pointers and a suggested fix. Work them in the order given.

## 2. Fixed in this branch
| ID | Sev | Where | Problem | Fix |
|---|---|---|---|---|
| S96-01 | Critical | `main.py::run_trading_cycle`, `analytics/trade_journal.py::TradeRecord.from_decision` | `from_decision()` always sets `result="OPEN"`; `main.py` saved it even when `exec_result["success"]` was False (quantity 0). | New `main._apply_execution_outcome_to_record()` sets `CANCELLED` on failure (journal stats already exclude `CANCELLED`). |
| S96-02 | Critical | `main.py::monitor_open_trades` | OPEN row + no exchange position ⇒ settled as WIN/LOSS from the mark price, even with `quantity<=0`. Counted by `JournalV2.get_consecutive_losses()` ⇒ `RiskEngine` blocked trading. | Rows with `quantity<=0` are healed to `CANCELLED` (exit=entry so rr=0, pnl=0) and skipped. Also heals phantom rows already in an existing DB. |
| S96-03 | High | `execution/trade_manager.py::execute_trade` | Emergency close after a failed SL ignored `close_position()`'s return (None on failure) yet raised "naked position closed for safety". | Return value checked; on failure logs CRITICAL, sets `result["naked_position_open"]=True`, error says `NAKED POSITION STILL OPEN — manual close required`. Success path message unchanged (existing tests rely on it). |
| S96-04 | Medium | `execution/trade_manager.py::_is_duplicate_order_error` | Only `-2010`/`-4015` recognised as "duplicate clientOrderId". | Also `-4116` (+ "duplicate" in message). **The code `-4116` is from memory of Binance's USDS-M futures error table and was NOT re-verified against the docs — verify before relying on it.** |

Tests: `tests/test_v16_s96_failed_trade_phantom_loss.py` (9 tests; 7 fail on the pre-fix code, incl. "three failed orders do not trip the loss streak").
Suite: baseline 3560 passed / 3 failed → after 3569 passed / 3 failed (the same 3 in `tests/test_dashboard_serving.py`, which need a built `dashboard/`; environmental, pre-existing). ruff clean on changed files.

## 3. Open (NOT fixed) — in priority order
| ID | Sev | Where | Problem | Suggested fix |
|---|---|---|---|---|
| R-01 | High | `main.py::monitor_open_trades` | Trade outcome is a heuristic: WIN if mark within 0.5 % of TP else LOSS; pnl = (mark−entry)·qty at *check time*. A TP hit followed by a pullback before the next check is recorded as LOSS; fees/funding ignored; trailing/manual exits mislabeled. Feeds RiskEngine and the learning pipeline. | Read realized PnL + exit price from Binance `userTrades` / income (`REALIZED_PNL`, `COMMISSION`, `FUNDING_FEE`) per closed trade; keep heuristic only as fallback. |
| R-02 | High | `main.py` (~L1470-1520), `TradeRecord.from_decision`, `execute_trade` | Journal and `TRADE_EXECUTED` use the signal's `decision.entry_price`, not the fill. USDS-M MARKET orders default to an ACK-style response (no `avgPrice`/`executedQty`) — **verify against a real response**. `execution_orchestrator.py` ~L127 (`avgPrice or price`) has the same weakness. Slippage/R-multiples are wrong. | After entry, `query_order(origClientOrderId=...)` (or `newOrderRespType="RESULT"`), store `avgPrice`/`executedQty`; verify filled qty before placing SL/TP and size SL/TP to the filled qty. |
| R-03 | Medium | `execute_trade` → `cancel_all_orders()` | Cancels *all* open orders for the symbol before entry, including SL/TP of an already-open position if two pipelines overlap. | Refuse to enter (or skip the cancel) when a position already exists for the symbol; check via `get_position_info(symbol)`. |
| R-04 | Medium | `main.py` Commander gates (pause / lifecycle, both in `run_trading_cycle` and the pre-execution check) | `except Exception: logger.debug(...)` ⇒ if control-state breaks, a PAUSED/STOPPED bot keeps trading, silently. Fail-open is documented as intentional ("must never block trading") — **owner decision needed**. | Fail-closed for the *execution* gate at least, and log at ERROR. |
| R-05 | Medium | `main.py::build_system` | Legacy single-symbol loop (`dp.get_position_info()`, `settings.SYMBOL` only) and `ExecutionScheduler` (own `PortfolioState`) share no position state; both on ⇒ possible double entry on one symbol. Code comments acknowledge "two separate pipelines". | Refuse to start both for overlapping symbols, or give the legacy loop the scheduler's `PortfolioState`. |
| R-06 | Medium (security) | `main.py::_start_api_server` (default `host="0.0.0.0"`, call at ~L2319 passes none), `_boot_login_url` | API binds all interfaces by default while the code's own comments say "localhost only"; browser auto-login puts the highest-privilege API key in `?token=` (address bar/history). | Default `127.0.0.1` (opt-in env for LAN); drop the token-in-URL flow or use a one-time exchange code. |
| R-07 | Low | repo root | Empty `FETCH_HEAD` and several `*.bundle` files are committed. A pattern scan of the last 300 commits found no API-key-shaped strings (limited scan). | Delete `FETCH_HEAD`; run a full secret scan (e.g. gitleaks) over all history before keeping the repo public. |
| R-08 | Low | `run_trading_cycle` | `trade_manager` heartbeat is beaten at cycle start regardless of work done, so the watchdog can't see a stuck execution layer. | Beat only after a real execution attempt/health probe. |
| R-09 | Low | `data/binance_provider.py::get_position_info`, `place_*` | Returns the first non-zero position and uses `closePosition=true` without `positionSide`; breaks in Hedge Mode (unverified — depends on account setting). | Assert One-way mode at startup (`GET /fapi/v1/positionSide/dual`). |
| R-10 | Low | pyflakes | Unused locals (`main.py` monitor `sl`, `bus`), `global _RUNNING` unused in `main.py`, plus others in `agents/*`, `api/app.py`. | Clean up under ruff. |
| R-11 | Info | §95 PATCH_NOTES | With `API_AUTH_ENABLED=false` the dashboard never opens `/ws/*` (documented, deliberately left). | Separate decision. |

## 4. Audit scope — what was and was NOT read
Read in full or in the relevant parts: `main.py` (build_system, run_trading_cycle, monitor_open_trades), `execution/trade_manager.py`, `analytics/trade_journal.py` (`TradeRecord`),
`journal/journal_v2.py` (`update_trade_result`, `get_consecutive_losses`), `data/binance_provider.py` (balance/position reads), repo conventions (`CLAUDE.md`, rules doc).
**Not audited (50k LOC repo):** `execution/execution_orchestrator.py`, `execution_scheduler.py`, `trade_lifecycle.py`, `risk/risk_engine.py` (beyond how it calls the journal),
`portfolio/*`, `scanner/*`, `ranking/*`, `agents/*`, `decision/*`, `regime/*`, `features/*`, `ml/*`, `learning/*`, `system_health/*`, `api/*`, `world/*`, dashboard frontend.
No live/testnet exchange was available: every exchange-behaviour claim (R-02 ACK response, `-4116`, R-09) is from documentation/memory and marked as needing verification.
Retracted from the first-pass chat review: "position check fails silently" (`get_position_info` raises; the cycle then ends with an error log — safe) and "-1021 is not retried" (it is in `utils/retry.py`'s retryable set).

## 5. How to continue
1. `git fetch` this bundle → `git checkout fix/failed-trade-phantom-loss-s96`; read this file, `PATCH_NOTES.md`, `docs/architecture.md` §96.
2. Work one open item per PR (project rule: feature branches, one commit per PR, update `CHANGELOG.md`, `docs/architecture.md`, `PATCH_NOTES.md`, `MIGRATION.md`, run `ruff` + `pytest tests -q`).
3. Suggested order: R-02 → R-01 (they share the "know the real fill/exit" plumbing) → R-03/R-05 → R-04 (needs owner decision) → R-06 → rest.
4. Never modify RiskEngine/Execution blindly (CLAUDE.md): inspect first, add tests that fail on the old code (pattern used in `tests/test_v16_s96_failed_trade_phantom_loss.py`).
