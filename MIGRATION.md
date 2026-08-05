# MIGRATION — Live-Trading Risk Hardening (BUG-LIVE-RISK-01..04)

## Do you need to do anything?

**Yes, one thing, only if you rely on the old auth default.** Everything
else is additive and requires no action.

### 1. `API_AUTH_ENABLED` now defaults to `True` (was `False`)

If your `.env` does **not** already set `API_AUTH_ENABLED` explicitly,
the dashboard API will now require an API key/JWT on every non-public
route after this patch, where it previously required nothing.

- **If you want the new (secure) behavior** — the default — just make
  sure `API_KEYS` and `JWT_SECRET` are configured in `.env` before you
  next restart. If they aren't configured, every request except the
  small public set (`/api/health`, `/api/auth/token`, the SPA shell
  pages) will start returning 401s.
- **If you want the old (no-auth) behavior** — e.g. a local-only
  dashboard where auth is genuinely unnecessary — set
  `API_AUTH_ENABLED=false` explicitly in `.env`.
- **If you run `EXECUTION_MODE=live`:** you can no longer start with
  `API_AUTH_ENABLED=false`, even if you set it explicitly. `api/app.py`
  now refuses to start at all in that combination — real-money live mode
  can no longer serve an unauthenticated dashboard. `EXECUTION_MODE=paper`
  and `EXECUTION_MODE=testnet` are unaffected by this specific check and
  may still run without auth if you choose.

Nothing else about the auth system changed — `api/auth.py`, token
issuance/rotation, and role enforcement are all exactly as before.

### 2. New operational concept: orphan-position hold

If `system_health/recovery_engine.py`'s reconciliation ever detects a
real exchange position with no journal record (pre-existing position,
or one opened outside the bot's lifecycle), the bot will now, on its
own:

1. Auto-place a protective stop-loss on it.
2. Block all new trade entries (`RiskEngine.can_trade()` returns `False`)
   until a human clears the hold.

**You will need to acknowledge this manually if it ever fires** — it
will not clear itself, including across restarts and day boundaries.
Check current status:

```
GET /api/system/reconciliation
```
→ `data.orphan_hold` is `null` if nothing is held, otherwise a dict with
`symbol`, `direction`, `qty`, `entry_price`, `sl_price`, `sl_placed`,
and `reason`.

Clear it once you've confirmed the position is handled (OPERATOR role
required):

```
POST /api/system/reconciliation/acknowledge
```

This does not re-verify exchange state on its own — it trusts that a
human reviewed the situation before calling it.

## What did NOT change

- No database schema changes, no new tables.
- No change to `RiskEngine.can_trade()`'s signature or return contract
  (`tuple[bool, str]`) — only new internal logic ahead of the existing
  checks. `portfolio/capital_manager.py` and every other caller are
  unaffected.
- No change to `TradeManager.execute_trade()`'s signature or public
  contract — the leverage fix is entirely internal to the method body.
- Paper mode (`EXECUTION_MODE=paper`) behavior is unchanged by
  BUG-LIVE-RISK-01's fail-fast check (it only fires for `live`).
- `place_stop_loss`, `place_take_profit`, `place_market_order` — their
  retry budgets and circuit-breaker wiring are untouched. Only
  `close_position`'s retry budget changed.

## Rollback

Every change in this bundle is additive/internal-logic-only — there is
no data migration to reverse. Reverting the commit is sufficient if
needed; nothing here depends on external state created by this patch
(the orphan-hold, if any, lives only in the running process's memory,
not persisted storage).
