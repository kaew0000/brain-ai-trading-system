# C1 — Exchange State Manager (ESM)

**Status:** v2 (this is a rewrite from scratch of an earlier v1 draft that
was reviewed and rejected before merge — see "History" below). Read-only.
Additive only. Nothing in the trading engine's decision path depends on
this package.

## 1. Purpose

Single source of truth for "what does the exchange say our account /
positions / orders look like right now", for read-only consumers: World
(C2 Position Lifecycle rendering), Dashboard (C3), CEO/AI context (C4).

## 2. Design principles (all enforced in the actual code, not aspirational)

- **Thin orchestration only.** `exchange_state/manager.py` never touches
  `UMFutures` or raw Binance JSON. It calls exactly two methods on the
  existing `BinanceDataProvider`: `get_account_snapshot()` and
  `get_open_orders()` (both new, additive, in `data/binance_provider.py`).
  Those two methods are the *only* place Binance JSON gets parsed —
  reusing the exact dict-shape convention `get_account_balance()` /
  `get_position_info()` already established, not a second parser.
- **One snapshot, one cache.** `ExchangeSnapshot` (in
  `exchange_state/models.py`) carries account + positions + orders
  together. There is deliberately no separate account-cache /
  position-cache / order-cache to keep in sync with each other.
- **One refresh = 2 upstream calls, not N.** `refresh()` calls
  `get_account_snapshot()` (which itself is one `/fapi/v3/account` call —
  Binance returns positions embedded in that response) plus
  `get_open_orders()` (one `/fapi/v1/openOrders` call). It does not fetch
  account, positions, margin, and orders as four separate round trips.
- **No funding rate.** Funding is market data, not exchange/account
  state — it stays in the market-context/feature layer. C1 does not
  model it.
- **Mode isolation.** One `ExchangeStateManager` instance per
  `(mode, exchange, account_id)`, via the `get_manager()` singleton
  registry. `paper`/`testnet`/`live` snapshots are different Python
  objects; there is no shared cache key across modes.
- **Immutable snapshots.** `AccountSnapshot`, `PositionSnapshot`,
  `OrderSnapshot`, `ExchangeSnapshot` are all `@dataclass(frozen=True,
  slots=True)`. A reference handed to a caller never changes under it.
- **Thread safety.** One `threading.RLock` per manager guards
  refresh/cache-read; snapshot objects themselves are immutable so
  reading them needs no lock.
- **Non-fatal errors.** A failed refresh never raises to the caller: it
  returns the previous snapshot marked `degraded=True` with a
  `stale_reason`, or — if there's no previous snapshot yet — an explicit
  empty/zeroed snapshot with `health_score=0`. Callers never null-check.

## 3. What's on `ExchangeSnapshot`

```
mode, exchange, account_id            # identity — matches the manager's key
account: AccountSnapshot              # wallet/margin totals
positions: dict[symbol -> PositionSnapshot]
orders: tuple[OrderSnapshot, ...]

revision: int                         # increments on every successful refresh
snapshot_uuid: str                    # unique per snapshot, for tracing
fetched_at: float

sync_reason: str        # startup | manual | scheduled | reconnect | order_fill
last_sync_source: str    # rest | websocket | recovery | reconnect (currently
                          #   always "rest" — no websocket source wired yet)
degraded: bool
stale_reason: str | None # timeout | rate_limit | network | maintenance | None
health_score: int        # 0-100 — see §5, this is a simple heuristic
```

`PositionSnapshot.version` increments only when that symbol's
`(side, quantity, entry_price)` actually changes between refreshes — not
on every refresh — so a consumer can cheaply detect "did this position
change" without diffing every field itself. If a position closes and a
different one later opens on the same symbol, its version tracking resets
to 1 (it is not a running counter across unrelated positions).

## 4. Data flow

```
get_snapshot()
  ├─ cache fresh (age < ttl_seconds)? → return cached ExchangeSnapshot
  └─ else → refresh(reason=...)
              ├─ dp.get_account_snapshot()   (1 call: wallet + margin + positions)
              ├─ dp.get_open_orders()        (1 call: all open orders)
              ├─ success → build new immutable ExchangeSnapshot, revision += 1
              └─ failure → _handle_refresh_failure()
                              ├─ prior snapshot exists → return it with
                              │     degraded=True, stale_reason=<classified>,
                              │     health_score capped down
                              └─ no prior snapshot → empty snapshot,
                                    degraded=True, health_score=0
```

## 5. Health score

A simple heuristic, not an engineered SLO metric: `100` on a clean
refresh; on repeated failures with a stale fallback available,
`max(20, 100 - 20 * consecutive_failures)`; `0` when there's no data at
all to fall back on. Good enough for a dashboard indicator; not intended
to drive automated decisions.

## 6. What ESM is explicitly NOT responsible for

Trade execution, risk calculation, position management, or recovery
actions. Those all remain in `execution/`, `risk/`, and
`system_health/recovery_engine.py`. C1 is read-only end to end.

## 7. History

A first draft (produced externally, referred to in review notes as "C1
v1") called `trade_client`/Binance JSON directly from inside the manager,
duplicated parsing logic that already existed in `BinanceDataProvider`,
split the cache into six separate per-field caches, included funding rate
as exchange state, and refreshed account/position/margin/orders as four
independent calls. The repo owner reviewed it, scored it below the merge
bar, and specified the v2 constraints this document describes. This
implementation was written from scratch against those constraints and
against the actual current `BinanceDataProvider`/`UMFutures` API surface
(verified by inspection, not assumed) — none of the v1 draft's code was
reused.

## 8. Testing

- `tests/test_exchange_state_models.py` — frozen dataclasses, `is_sl`/`is_tp`
  classification, snapshot lookups/defaults.
- `tests/test_exchange_state_manager.py` — cache hit/TTL-expiry/force-refresh,
  exactly-2-calls-per-refresh, position versioning (including
  close-then-reopen reset), degraded/stale fallback (with and without a
  prior snapshot), recovery clearing `degraded`, mode isolation, the
  `get_manager()` registry, and concurrent-refresh/concurrent-read thread
  safety.
- `tests/test_binance_provider_c1_additions.py` — the two new provider
  methods: totals parsing, zero-position filtering, LONG/SHORT side
  derivation, symbol-filtered vs. unfiltered open-orders calls.

Full suite after this change: `pytest -m unit -q` → all passing (see
CHANGELOG.md for the exact count at merge time). `ruff check` and
`vulture --min-confidence 80` both clean on every new/changed file.
