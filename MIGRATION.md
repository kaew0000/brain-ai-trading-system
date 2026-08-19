# MIGRATION — V16 Phase 4C: Dashboard Session Persistence

## Do you need to do anything?

**One new setting to check, nothing to run.** Unlike the companion
database-migration phase, there's no data to migrate — this only
changes how the dashboard's session works.

Add to `.env` (or confirm the defaults already suit you):

```
JWT_REFRESH_EXPIRY_DAYS=7
COOKIE_SECURE=true
```

- `JWT_REFRESH_EXPIRY_DAYS` — how many days the dashboard stays signed
  in across page refreshes/browser restarts before the operator needs
  to re-enter their API key again. Default 7; raise or lower to taste.
- `COOKIE_SECURE` — **leave `true` for any real deployment.** Only set
  to `false` if you're running the dashboard locally over plain
  `http://` (e.g. `http://localhost:8000`) for dev/testing — browsers
  silently refuse to persist a `Secure` cookie over a non-HTTPS
  connection, which would silently break session persistence (the
  operator would still be forced to log in on every refresh, exactly
  the bug this phase fixes) with no visible error. If your dashboard is
  served over `https://`, or through a reverse proxy that terminates
  TLS, leave this `true`.

No database changes. No new dependencies (`PyJWT` was already a
dependency, used for the existing bearer token). Rebuild the dashboard
(`npm run build` in `dashboard_src/`) and restart the API process to
pick this up — same as any other Track A + Track B change.

## What actually changed, mechanically

Before: the dashboard's session token lived only in browser JS memory,
by design (to keep it safe from XSS-based theft — never in
`localStorage`/`sessionStorage`). A page refresh always cleared it, and
nothing existed to restore a session afterward, so every refresh forced
a fresh login with the operator's API key.

After: login also sets a **separate**, longer-lived refresh token as an
`httpOnly` cookie — a credential page JavaScript can never read, XSS
included, so this doesn't reopen the risk the original in-memory design
was avoiding. On page load, the dashboard silently exchanges that
cookie for a fresh session token via a new endpoint
(`POST /api/auth/session`) — no login form, no API key re-entry. The
refresh cookie itself rotates (is replaced) every time it's used, so a
copied/leaked cookie value only works once. Logging out now actually
ends the session server-side (revokes both the cookie and the current
session token) instead of only clearing local browser state.

## Rollback

Revert the changes to `api/auth.py`, `api/app.py`,
`dashboard_src/src/lib/api.ts`, `dashboard_src/src/stores/index.ts`,
`dashboard_src/src/components/layout/Layout.tsx`, and
`dashboard_src/src/components/auth/LoginModal.tsx`. Remove
`JWT_REFRESH_EXPIRY_DAYS` / `COOKIE_SECURE` from `config/settings.py`
and `.env` (harmless to leave them — unused settings, nothing reads
them if the rest is reverted). Rebuild the dashboard and restart.

Any refresh-token cookies already issued to browsers become simply
unrecognized after a rollback (the endpoint that reads them,
`POST /api/auth/session`, no longer exists) — browsers hold onto the
cookie until it expires naturally (`JWT_REFRESH_EXPIRY_DAYS`) or the
user clears cookies; it has no effect once nothing reads it. No manual
cleanup needed.

## What this does not fix

- The separate database-migration issue — see the companion
  `feature/db-migration-auto-runner` phase's own `MIGRATION.md`.
- See `PATCH_NOTES.md`'s "What this does not do" for the reasoned-through
  scope boundaries (reuse-detection/breach-alerting, CSRF tokens,
  split-origin deployment) — none of these are gaps that were missed,
  they're documented, deliberate stopping points for this phase.
