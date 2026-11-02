# V16 §97 — Bug audit status & hand-off (supersedes the open-list in `V16_BUG_AUDIT_S96.md`)

Date: 2026-11-02 · Branch: `fix/real-fill-and-realized-pnl-s97` · Base: `main` @ `0a99e76` (PR #137 = §96 merged) · Next PR number: **#138**
Method: real clone, code read, pytest. No live/testnet exchange was available — every claim about Binance behaviour is marked.

## 1. Status of every item found so far
| ID | Sev | Status | Where fixed / notes |
|---|---|---|---|
| S96-01 failed order journaled OPEN → phantom LOSS | Critical | **Fixed (§96, PR #137)** | `main._apply_execution_outcome_to_record` |
| S96-02 monitor settles qty≤0 rows | Critical | **Fixed (§96)** | `monitor_open_trades` heals to CANCELLED |
| S96-03 emergency-close result ignored | High | **Fixed (§96)** | `TradeManager.execute_trade` |
| S96-04 `-4116` duplicate clientOrderId | Medium | **Fixed (§96), code unverified** | `_is_duplicate_order_error` — verify `-4116` against Binance's USDS-M error table |
| **R-01** outcome = mark-price heuristic | High | **Fixed (§97)** | new `journal/exit_truth.py`; `monitor_open_trades` prefers real fills, falls back to the old heuristic |
| **R-02** journal stores signal price/qty, not the fill | High | **Fixed (§97)** | `TradeManager._confirm_entry_fill`; `TradeRecord.from_decision`; `ExecutionOrchestrator` open path |
| S97-01 §96 side effect: all rows healed ⇒ mission cleared without a close | Low | **Fixed (§97)** | loop-carried `result/pnl/exit_px` initialised; mission block guarded (introduced by my own §96 `continue`; found while wiring R-01) |
| R-03 `cancel_all_orders()` before entry can strip SL/TP of an existing position | Medium | **Open** | refuse entry (or skip cancel) when `get_position_info(symbol)` shows a position |
| R-04 Commander pause/lifecycle gates fail-open (`except: logger.debug`) | Medium | **Open — needs owner decision** | design comment says fail-open is intentional |
| R-05 legacy single-symbol loop and `ExecutionScheduler` share no position state | Medium | **Open** | refuse to run both on overlapping symbols or share `PortfolioState` |
| R-06 API binds `0.0.0.0` by default; `_boot_login_url` puts the API key in `?token=` | Medium (security) | **Open** | default `127.0.0.1`; drop token-in-URL |
| R-07 empty `FETCH_HEAD`, `*.bundle` committed | Low | **Open** | delete; run a full-history secret scan (limited scan of last 300 commits found nothing) |
| R-08 `trade_manager` heartbeat beaten at cycle start | Low | **Open** | |
| R-09 Hedge Mode unsupported (`closePosition` without `positionSide`, first non-zero position) | Low | **Open, unverified** | assert One-way mode at startup |
| R-10 unused locals / `global _RUNNING` / pyflakes noise | Low | **Open** | ruff cleanup |
| R-11 dashboard never opens `/ws/*` when `API_AUTH_ENABLED=false` | Info | **Open (documented in §95)** | |
| R-12 `CloseSource` is still inferred from WIN/LOSS (TAKE_PROFIT vs STOP_LOSS) even when the real exit price is known | Low | **Open** | with `exit_truth` the exit price vs entry/SL/TP can name the real source |

## 2. What §97 changed (behaviour)
* **Entry (R-02).** After the market order, `TradeManager` reads back `status/executedQty/avgPrice` (uses the order response if it is already a priced FILLED order; otherwise polls `query_order` ≤3×, only while the order is NEW/PARTIALLY_FILLED; stops on any unusable payload). Result gains `fill_price`, `filled_qty`, `fill_confirmed`, `slippage_pct`. If the order is terminal-unfilled (`CANCELED/EXPIRED/REJECTED`, executedQty 0) the trade aborts **before** SL placement. If the read-back fails, the trade proceeds exactly as before with `fill_confirmed=False`.
* **Journal.** When `fill_confirmed`, `TradeRecord.from_decision` and the orchestrator open-path store the real fill price/qty; slippage on the orchestrator path is now computed (it was always `None` for ACK-style responses). `TRADE_EXECUTED` carries the real `entry_price`, plus `signal_price`/`slippage_pct`.
* **Exit (R-01).** `journal/exit_truth.resolve_realized_exit()` anchors on the journaled entry `order_id`: entry fills (`userTrades?orderId=`) give the exact exchange time; closing fills are the opposite-side fills after it, accumulated chronologically until the trade's qty is closed (a later trade on the same symbol is never attributed). Exit price = qty-weighted average; PnL = Σ`realizedPnl` − commissions (entry + exit) when all commissions are in one asset, else gross. Returns `None` (⇒ old mark-price heuristic) when: no/invalid entry order id, API error, closing qty < 99.5 % of the journaled qty (partial close, or held beyond `userTrades`' 7-day window), malformed data. Never raises, no retries (same single-attempt rule as `journal/fee_backfill.py`).
* **PnL semantics.** For trades resolved from fills, `pnl` is now **net of commissions** (consistent with `paper/paper_position.py`, which was already net). No live consumer computing `pnl − fees` was found (grep, not exhaustive) — check before adding one, or it would double count.

## 3. Known limits / needs verification on a real account (testnet first)
1. Assumed from Binance docs/memory, **not tested live:** USDS-M MARKET responses are ACK-style (no `avgPrice`); `userTrades` fields `side/price/qty/realizedPnl/commission/commissionAsset/time/id`; `userTrades` with `startTime` only returns ≤7 days; `-4116`.
2. `exit_truth` needs `trades.order_id` — both journaling paths set it; legacy rows without it use the fallback.
3. Fees in BNB (or mixed assets) ⇒ `fees=None`, PnL stays gross; no price conversion is attempted.
4. SL/TP are `closePosition` orders, so a **partial entry fill** is covered automatically; the journal records the filled qty and a warning is logged. Partial fills are not otherwise handled (no top-up).
5. `journal/fee_backfill.py` still documents "exit fees unrecoverable for the classic loop" — that is now closable (the fills are fetched in `exit_truth`), but persisting `fees` into execution attribution was left out of scope.

## 4. Audit scope (unchanged from §96 — still NOT read in full)
`execution/execution_scheduler.py`, `trade_lifecycle.py`, `risk/risk_engine.py` (beyond its journal calls), `portfolio/*`, `scanner/*`, `ranking/*`, `agents/*`, `decision/*`, `regime/*`, `features/*`, `ml/*`, `learning/*`, `system_health/*`, `api/*`, `world/*`, dashboard frontend. Read this round in addition: `execution/execution_orchestrator.py` open path, `journal/fee_backfill.py`, `analytics/trade_journal.py::from_decision`.

## 5. How to continue
`git fetch` the bundle → `git checkout fix/real-fill-and-realized-pnl-s97` → read this file + `PATCH_NOTES.md` + `docs/architecture.md` §97. One open item per PR; project rules: single commit, update `CHANGELOG.md`, `docs/architecture.md`, `PATCH_NOTES.md`, `MIGRATION.md`, `ruff` + `pytest tests -q`. Suggested order: **testnet-verify §97 assumptions (§3.1)** → R-03/R-05 → R-12 → R-04 (owner decision) → R-06 → rest.
