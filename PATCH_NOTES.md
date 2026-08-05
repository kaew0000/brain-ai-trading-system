# PATCH NOTES — Live-Trading Risk Hardening (BUG-LIVE-RISK-01..04)

Branch: `feature/live-trading-risk-hardening`
Base: `main` (post PR #29 / BUG-V16-BP-05 merge, commit `fdf864f`, 1918 passing)
Track: A (backend/engine) only — no Track B (`world/`) files touched.
Source: `KNOWN_BUGS_LIVE_TRADING_RISK.md`, a 4-item bug list found via
source inspection of `main` *after* BUG-V16-BP-05 landed (i.e. these are
independent of, and not fixed by, PR #29).

## Summary

Four real-money-risk bugs found and fixed in one bundle, each verified
independently against a fresh clone of `main` before any code was
written. All four were confirmed still present as described in the
source report; findings and the exact fix chosen for each were confirmed
with the repo owner before implementation (auth: flip default + fail-fast
on live; orphan position: auto-protect + hold-until-acknowledged;
leverage: re-query and size against actual).

## BUG-LIVE-RISK-01 — Dashboard API had no authentication by default

**Root cause:** `config/settings.py`'s `API_AUTH_ENABLED` defaulted to
`False`, and nothing stopped `EXECUTION_MODE=live` from running with it
left at that default. Auth machinery (`api/auth.py`) already existed and
worked correctly — it just wasn't on unless an operator remembered to
flip it in `.env`.

**Fix:**
- `config/settings.py`: `API_AUTH_ENABLED` now defaults to `True`.
- `api/app.py`'s `lifespan()`: refuses to start (`RuntimeError`) if
  `EXECUTION_MODE=live` and `API_AUTH_ENABLED=false`, regardless of how
  it got that way. Checked at server-startup time, not at bare import, so
  importing `api.app` for tests/introspection never raises.
- `conftest.py`: new autouse fixture pins the *test-time* default back to
  `False` (matching the old behavior) so the ~18 other test files with
  unauthenticated `TestClient(app)` calls don't need individual changes.

## BUG-LIVE-RISK-02 — Pre-existing/orphaned exchange positions got zero automatic protection

**Root cause:** `system_health/recovery_engine.py`'s
`attempt_reconciliation_recovery()` only handled the "ghost journal row"
case (journal thinks a position is open, exchange is flat). The opposite
and more dangerous case — a real exchange position with no journal
record at all (pre-existing before this bot session, or opened outside
the bot's lifecycle) — fell through to `"no_safe_auto_action"` with
nothing beyond a log line. No SL/TP, no alert, no block on new entries.

**Fix:**
- `system_health/recovery_engine.py`: new
  `_protect_orphaned_exchange_position()` — re-queries the live position,
  auto-places a protective SL sized off `settings.RISK_PER_TRADE_MAX`
  (same convention `TradeManager.calculate_position_size()` already
  uses), and sets a hold via the new `RiskEngine.set_manual_hold()`.
  Idempotent: won't re-place a second SL on repeated cycles for the same
  position. New `acknowledge_orphaned_position()` clears the hold —
  intended to be called by a human after they've reviewed the position,
  not automatically.
- `risk/risk_engine.py`: new manual-hold mechanism
  (`set_manual_hold`/`clear_manual_hold`/`has_manual_hold`), checked
  first in `can_trade()`. Deliberately separate from the existing
  `disable_trading_today()` — that auto-clears at the UTC day boundary
  (correct for daily-loss limits), which would be wrong here; an
  unprotected position must stay blocked across day boundaries until a
  human clears it.
- `api/app.py`: `GET /api/system/reconciliation` now includes an
  `orphan_hold` field. New `POST /api/system/reconciliation/acknowledge`
  (OPERATOR role required) clears the hold.

## BUG-LIVE-RISK-03 — Leverage-change failure was logged but never checked before sizing

**Root cause:** `execution/trade_manager.py`'s `execute_trade()` called
`self.set_leverage(...)` and discarded its bool return value, then sized
the position against the *intended* leverage regardless of whether the
exchange call actually succeeded (e.g. `"Margin type cannot be changed if
there exists position"`). Could silently size a larger notional than the
account actually supports at the leverage it's really running at.

**Fix:** `execute_trade()` now checks `set_leverage()`'s return. On
failure, new `_query_actual_leverage()` re-queries the exchange's real
current leverage via `get_position_risk()` and sizes against that instead
of the intended value. If the re-query itself can't be verified, the
trade aborts (`RuntimeError`) rather than guessing. `_query_actual_leverage()`
re-raises retryable `ClientError`s (same classification helper
`close_position`/`place_market_order` already use) so its own
`@retry_api_call(retries=3)` is real — silently swallowing them would be
BUG-V16-EXEC-01(b) again, just relocated.

## BUG-LIVE-RISK-04 — Emergency close had a lower retry budget than the SL it's a fallback for

**Root cause:** `close_position()` — the call used to flatten a naked
position when SL placement fails after all of `place_stop_loss`'s
retries — had `retries=2, delay=2.0`, lower than `place_stop_loss`'s
`retries=5, delay=3.0`. The fallback was more likely to give up than the
thing it's a fallback for.

**Fix:** `close_position()`'s retry budget aligned to `retries=5,
delay=3.0`, matching `place_stop_loss`. Deliberately did **not** add
`breaker=_TRADE_BREAKER` (unlike `place_stop_loss`/`place_market_order`/
`place_take_profit`): if the breaker were already open from the
preceding SL failures, wrapping the emergency close in the same breaker
would fast-fail it instead of attempting it.

## Files changed

| File | Change |
|---|---|
| `config/settings.py` | `API_AUTH_ENABLED` default `False` → `True` |
| `api/app.py` | Fail-fast startup check; `orphan_hold` field + acknowledge endpoint |
| `risk/risk_engine.py` | New manual-hold mechanism |
| `system_health/recovery_engine.py` | New orphan-position auto-protect + hold |
| `execution/trade_manager.py` | Leverage re-query on failure; `close_position` retry budget |
| `conftest.py` | Autouse fixture preserving test-time auth-off default |
| `tests/test_api_auth.py` | Updated default-value test; new fail-fast tests |
| `tests/test_execution.py` | New `RiskEngine` manual-hold tests |
| `tests/test_v16_execution_idempotency.py` | New leverage re-query + retry-budget tests |
| `tests/test_recovery_engine.py` | **New file** — first-ever coverage for `RecoveryEngine` |
| `tests/test_audit_fixes.py` | New `orphan_hold` API tests |
| `docs/architecture.md` | New hotfix section |
| `CHANGELOG.md` | New entry |

## Testing

`pytest -m unit -q` → **1948 passed, 0 failed** (1918 baseline + 30 new).
`ruff check .` → clean, whole project. Verified in a second, independent
fresh clone (see MIGRATION.md) before commit.

## Known follow-up (not fixed here, out of scope for this bundle)

- The orphan-position protective SL is sized off `RISK_PER_TRADE_MAX`
  only — it does not also place a TP. Acceptable for a defensive action
  (limiting further loss matters more than locking in a target on a
  position the bot didn't open), but worth revisiting.
- `acknowledge_orphaned_position()` does not re-verify exchange state
  itself before clearing the hold — acknowledgement is a deliberate human
  judgment call, not an automatic re-check. If that's ever considered
  insufficient, a "re-verify flat or protected before allowing
  acknowledge" step would be a natural, separately-scoped follow-up.
- `tests/test_execution_factory.py` mutates `os.environ["EXECUTION_MODE"]`
  and `config.settings.EXECUTION_MODE` across several tests and never
  restores it (the file's last call happens to leave it at `"paper"`, so
  today this is latent, not active). Flagged during investigation of this
  bundle, not fixed — touching an unrelated test file's cleanup logic was
  out of scope here, and the new live-mode fail-fast check was
  deliberately written to read `EXECUTION_MODE` fresh from the
  environment each time rather than trust an import-time binding, which
  sidesteps the specific hazard this leak could otherwise cause.
