# PATCH NOTES — V16 Phase 4C: Dashboard Session Persistence

Branch: `feature/dashboard-session-persistence`
Base: `main` @ `8920cd7` (merge of PR #65, Train Monitor Dashboard Tab)

## Scope note

Requested directly, as the second of two problems reported together:
"พอรีเฟรชหน้า dashboard ต้อง login หน้าเว็ปใหม่" (refreshing the dashboard
page forces a re-login). Investigation found this is unrelated to the
database (see the separate `feature/db-migration-auto-runner` phase/
bundle, delivered first at the owner's request, merged as PR #66) —
root cause is entirely in the dashboard's session design. This phase
addresses only that.

Touches both Track A (`api/auth.py`, `api/app.py`, `config/settings.py`)
and Track B (`dashboard_src/`) — unavoidable, since a session-persistence
fix has to change how the frontend and backend agree on a session. Every
change is additive; nothing removed except one dead function (see
"Removed" below).

## `main` moved twice during this phase — integration, not just a rebase

Between starting this phase and delivering it, three more PRs were
merged upstream: #67 (`fix/dashboard-ws-auth-token-rotation`), #68
(Train Monitor decision log), #69 (confidence threshold configurable).
PR #67 is the one that mattered here — it touches the exact same area
of `dashboard_src/src/lib/api.ts` this phase does (`login()`, `logout()`),
fixing two different, real bugs: WebSocket channels never carrying a
token at all (so every `/ws/*` handshake was rejected from page load
onward, login or not), and the Bearer token never being proactively
refreshed before `JWT_EXPIRY_MINUTES` elapsed mid-session.

These are genuinely different problems from the one this phase fixes
(a page *refresh* forcing re-login) — not duplicate work — but both
needed to keep working together. This wasn't a docs-only conflict like
the Phase 1 rebase; it required actually reading PR #67's design
(`_scheduleRotate()`, `_notifyAuthChange()`, the `onAuthChange` pub/sub
`ManagedWS` and `stores/index.ts` both subscribe to) and integrating
`restoreSession()` into it correctly:

- `restoreSession()` now also calls `_scheduleRotate()` and
  `_notifyAuthChange('login')` on success. Without this, a session
  restored after a page refresh would never get proactive rotation
  scheduled (silently dying at the next `JWT_EXPIRY_MINUTES` boundary)
  and would never trigger `ManagedWS`'s reconnect-on-authenticated
  listener — every `/ws/*` channel would sit disconnected for the rest
  of that session, exactly the bug PR #67 had just fixed for the
  login-via-form path.
- `logout()`'s merge kept PR #67's `_clearRotateTimer()` +
  `_notifyAuthChange('logout')` (stops the rotation timer, disconnects
  `/ws/*`) alongside this phase's server-side revoke call.
- Found and fixed a real regression while integrating: the new
  `fetch(...).catch(...)` call in `logout()` crashed PR #67's own test
  file (`api.auth.test.ts`) with `TypeError: Cannot read properties of
  undefined (reading 'catch')` — its test doubles for `fetch` don't all
  return a real Promise. Fixed by wrapping in `Promise.resolve(...)`
  (see "Changed" below) rather than touching their test's mocking
  approach.
- Added one new test to `api.auth.test.ts` itself (not just my own new
  file) proving `restoreSession()` triggers the same WS-reconnect
  PR #67's own "reconnect the instant login succeeds" test proves for
  the login path — this integration seam needed its own coverage in
  the file that already has the `FakeWebSocket` harness for it, or a
  future regression here would have nothing to catch it.

Rebased onto current `main` (`4d6f21f`, includes PR #66/#67/#68/#69) so
this branch is a clean fast-forward — no `--force` needed to import
this particular bundle. If `main` has moved again by the time this is
imported, the standard `bundle_manager --force` path applies as usual.

## Root cause

`dashboard_src/src/lib/api.ts` holds the session Bearer JWT in a plain
JS variable, deliberately never in `localStorage`/`sessionStorage` — its
own docstring says so explicitly, to stop an XSS bug from being able to
exfiltrate a long-lived stolen session. That design is correct and is
**not** changed by this phase. But it also means the token is wiped on
every page reload (JS memory resets), and nothing existed to restore a
session afterward — so every refresh forced the operator to re-enter
their long-lived API key, even seconds after they'd just logged in.

## What changed

### Added — `api/auth.py`
- A **separate**, longer-lived refresh token (distinct from the bearer
  JWT — `"typ"` claim on both, cross-checked both directions so neither
  can be used as the other), delivered **only** as an httpOnly cookie.
  httpOnly means page JS cannot read it under any circumstances — XSS
  included — so restoring a session this way does not reopen the exact
  risk the in-memory-only bearer design was written to avoid.
- `issue_login_session()` — supersedes `issue_token_for_api_key()`
  (removed; had exactly one caller, now folded in — see "Removed"
  below), issues both tokens together.
- `refresh_session()` — exchanges a valid refresh token for a fresh
  bearer token. **Rotates on every use**: the presented refresh token is
  revoked and a new one issued alongside, so a given cookie value is
  only ever valid for a single silent re-auth (limits how long a
  leaked/stolen cookie value stays useful, without full reuse-detection/
  breach-alerting — see "What this does not do" below).
- `revoke_refresh_cookie()` / `revoke_bearer_from_header()` — best-effort
  revocation helpers for logout; safe to call with `None`/garbage input.
- Same in-memory revocation-registry pattern as the existing `_revoked_jti`
  (doesn't survive a process restart — already an accepted characteristic
  of this file, e.g. `JWT_SECRET` itself is ephemeral-per-process when
  unset).

### Added — `api/app.py`
- `POST /api/auth/session` — the dashboard calls this once on page load.
  Silently exchanges the refresh cookie for a fresh bearer token, no API
  key re-entry. 401 if there's no valid cookie — frontend treats that
  exactly like "not logged in," same LOGIN button as before this phase.
- `POST /api/auth/logout` — actually ends the session server-side
  (revokes the refresh cookie **and** the presented bearer token, then
  clears the cookie). Before this phase, logout only cleared local
  frontend state; the bearer token remained valid server-side until its
  own expiry regardless, and there was no cookie yet to worry about.
- `_set_refresh_cookie()` / `_respond_with_session()` — cookie is
  `httpOnly`, `samesite=lax`, `path=/api/auth` (narrowest scope that
  still works — never sent on any other route), `secure` follows the new
  `settings.COOKIE_SECURE` (default `true`).
- `/api/auth/token` unchanged in its JSON response shape (still exactly
  `{token, role, expires_at, jti}` — existing tests pass unmodified);
  the refresh token is stripped from the body and set as a cookie only.

### Added — `config/settings.py`, `.env.example`
- `JWT_REFRESH_EXPIRY_DAYS` (default `7`).
- `COOKIE_SECURE` (default `true` — must be set `false` in `.env` for
  local/dev over plain `http://`; browsers silently refuse to persist a
  `Secure` cookie over a non-HTTPS connection).

### Changed — `dashboard_src/src/lib/api.ts`
- New `restoreSession()`: calls `POST /api/auth/session` with
  `credentials: 'include'`. Resolves `true`/`false`, **never throws** —
  a network error or 401 both resolve `false` ("nothing to restore" is
  the ordinary, ~expected outcome for most page loads, not an error).
  On success, also calls PR #67's `_scheduleRotate()` and
  `_notifyAuthChange('login')` — see "`main` moved twice" above for why.
- `login()`: now sends `credentials: 'include'` so the browser actually
  stores the cookie the server sets. (Merged cleanly with PR #67's
  `_scheduleRotate()`/`_notifyAuthChange('login')` calls already there —
  adjacent, non-overlapping lines.)
- `logout()`: clears local state synchronously first (unchanged
  behavior/timing, and keeps PR #67's `_clearRotateTimer()` +
  `_notifyAuthChange('logout')`), then fires a best-effort
  `POST /api/auth/logout` in the background, wrapped in
  `Promise.resolve(...)` so a test double or non-standard fetch shim
  that doesn't return a real Promise can't throw synchronously out of
  logout() (found this the hard way — see above). Never throws even if
  the real network call fails — the cookie just expires on its own
  after `JWT_REFRESH_EXPIRY_DAYS` in that case.

### Changed — `dashboard_src/src/lib/tests/api.auth.test.ts` (PR #67's file)
- One new test: `restoreSession()` triggers the same WS-reconnect its
  own `login()` test already proves. See "`main` moved twice" above.

### Changed — `dashboard_src/src/stores/index.ts`, `Layout.tsx`
- `useAuth` gets a new `restoreSession` action, calling
  `api.restoreSession()` and populating `role`/`expiresAt` on success —
  silently, no error state set on failure.
- `Layout.tsx` (the app shell, mounted once) calls it in a `useEffect`
  on mount. Zero changes to `LifecycleControl.tsx` / the LOGIN-button
  display logic — deliberately left untouched (recently, carefully
  fixed in a prior phase per project history); while `restoreSession()`
  is in flight, `role` stays `null`, which is already exactly the
  existing "not logged in" state that component already renders
  correctly.

### Changed — `dashboard_src/src/components/auth/LoginModal.tsx`
- Copy updated from "your API key ... is never stored on this device"
  to reflect what's now literally true: the API key itself is still
  never stored, but a secure, revocable session now is — and that's
  what stops a refresh from logging the operator out.

### Removed — `api/auth.py::issue_token_for_api_key()`
- Superseded by `issue_login_session()`, which does the same API-key
  lookup plus refresh-token issuance. Confirmed (grep) it had exactly
  one caller anywhere in the codebase (`api/app.py`'s `auth_token()`
  handler, updated in this phase) and zero direct test references —
  keeping it alongside the new function would just be two near-identical
  "exchange a key for a token" entry points, and `vulture` would have
  flagged it as dead code once its one caller was updated.

## Verification

- Manual adversarial checks against a real `TestClient`, before writing
  formal tests: login sets the cookie → silent session-restore issues a
  *different* bearer token and rotates the cookie → new bearer token
  works on a protected route → a **rotated-away** refresh cookie replay
  is rejected (`refresh token revoked`) → a bearer token presented as
  the refresh cookie is rejected (`not a refresh token`) → a refresh
  token presented as a bearer header on a genuinely protected route is
  rejected (`refresh tokens cannot be used as a bearer token`) → logout
  clears the cookie and ends the session (subsequent `/api/auth/session`
  → 401).
- `pytest tests/`: **2605 passed** on the final, rebased-onto-current-main
  tree (verified true baseline on `main` @ `4d6f21f`: 2586 + 7 from the
  already-merged PR #66 + 12 new in
  `tests/test_api_auth.py::TestRefreshTokenSessionPersistence`), 45
  deselected (integration marker), zero regressions.
- `ruff check . --exclude dashboard_src --exclude dashboard`: clean,
  before and after.
- `vulture . --exclude dashboard_src,dashboard,tests --min-confidence 80`:
  clean, before and after (confirms the `issue_token_for_api_key`
  removal didn't leave anything else newly dead).
- `python3 -c "import main"`: OK.
- Frontend (`dashboard_src/`): `npx vitest run` — **95 passed** (78
  baseline + 6 from the already-merged PR #67 + 1 new integration test
  in that same file + 10 new in `src/lib/tests/api.test.ts`), zero
  regressions once the `Promise.resolve()` fix above was in.
  `npx tsc --noEmit` — clean (this project runs with `strict: false` in
  `tsconfig.json`, unchanged by this phase). `npm run build` — succeeds,
  production bundle unaffected in structure.
- Independent second-clone verification: see delivery message.

## What this does not fix / does not do

- Does not touch the separate database-migration issue — see
  `feature/db-migration-auto-runner`'s own `PATCH_NOTES.md`.
- No reuse-detection/breach-alerting on the refresh token: rotation
  limits a leaked cookie's usefulness (single-use per silent re-auth),
  but this phase doesn't detect or alert on a *rotated-away* token being
  replayed beyond simply rejecting the replay itself. A fuller
  implementation would flag that as a likely-compromise signal and force
  a full re-login across all of that operator's sessions. Deferred —
  meaningfully more complex, and this project has no existing
  alerting/notification infrastructure to plug it into yet.
- No CSRF token on `/api/auth/session` or `/api/auth/logout`. Reasoned
  through, not just skipped: `SameSite=Lax` already blocks the cookie
  from being attached to a cross-site `POST` in modern browsers, and
  `allow_credentials` is not set on the existing `CORSMiddleware`
  configuration (`allow_origins=["*"]`), so a cross-origin page can't
  read either endpoint's response even if a request somehow fired. Worst
  case for `/api/auth/logout` specifically is a nuisance (forced
  logout), not credential exposure.
- Cookie is scoped to same-origin deployment (the primary, existing
  topology — the FastAPI server serves the built dashboard directly).
  A split-origin deployment (dashboard on one host, API on another)
  would need `SameSite=None` + explicit origin allowlisting instead of
  `allow_origins=["*"]`, and `allow_credentials=True` — not implemented,
  since it's not how this system is actually deployed today.
