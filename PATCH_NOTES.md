# PATCH NOTES — Track B: LifecycleControl Unauthorized-State Visibility Fix

Branch: `fix/lifecycle-control-unauth-visibility`
Base: `main` @ `a88bb5b`

## Scope note

Not a numbered phase — reactive UI bugfix reported directly from a live
production session (Command Center screenshot: `localhost:8000`,
`OFFLINE`/`UNKNOWN` header, no visible control in the header bar other
than a stray browser tooltip reading "Login as OPERATOR to control the
bot"). Track B (`dashboard_src/`) only — zero Track A / `.py` files
touched, confirmed via `git diff --stat`.

## Root cause

`api/auth.py` enforces credentials on every `GET /api/*` route and
every `/ws/*` stream once `API_AUTH_ENABLED=true` (this deployment: `1
API key(s) configured`, per the reported startup log) — there is no
anonymous tier below VIEWER by design. A freshly loaded dashboard has
`useAuth().role === null`, so `GET /api/command/state` 401s and
`useCommander().state` stays `undefined` forever until login.

`lifecycleButtonSpec(undefined)` (`dashboard_src/src/lib/lifecycleControl.ts`)
correctly returns its "unconfirmed state" default: `{ label: '…', tone:
'transitioning', disabled: true }` — muted colors, `cursor-wait`. A
prior fix (`fix/lifecycle-control-login-lockout`, already on `main`)
correctly made this button *clickable* while unauthorized via
`lifecycleButtonInert()`, so it still opens the login modal — but
`LifecycleControl.tsx` kept sourcing the button's visible label/tone
straight from `spec` regardless of auth state. Because `spec.disabled`
is `true` in this default case, the old `!authorized && !spec.disabled
? ' 🔒' : ''` suffix never rendered either. Net result: a real,
correctly wired, clickable `<button>` with no visible affordance —
label `…` in muted gray with a "wait" cursor — which reads as "loading,
inert," not "click to log in." That is what the report describes as
the start/stop/login button "not showing."

This is a visual-affordance gap only. The click handler, the login
modal, and the actual START/STOP command flow were already correct.

## Fix

`dashboard_src/src/lib/lifecycleControl.ts` — added (additive, no
existing export touched) `lifecycleButtonDisplay(spec, authorized,
pending)`: while unauthorized, always returns `{ label: 'LOGIN', tone:
'login' }`, fully decoupled from `spec` (mirrors `handleClick()`'s
existing posture, which never consults `spec.command` until after the
authorized check). Once authorized, returns `spec`'s own label/tone
unchanged — the authorized START/STOP/RESTART/pending flow is
byte-for-byte identical to before this patch.

`dashboard_src/src/components/commander/LifecycleControl.tsx` — added
one new `login` entry to `TONE_CLASS` (`accent-blue`, clearly distinct
from the muted "transitioning" style, no `cursor-wait`); button now
renders `display.label` / `TONE_CLASS[display.tone]` from the new
function instead of `spec.label` / `TONE_CLASS[spec.tone]` +
manual 🔒-suffix logic. `lifecycleButtonSpec()` and
`lifecycleButtonInert()` are untouched.

## Files changed

- `dashboard_src/src/lib/lifecycleControl.ts` (+43 lines, additive export)
- `dashboard_src/src/components/commander/LifecycleControl.tsx` (+7/-4 lines)
- `dashboard_src/src/lib/tests/lifecycleButtonDisplay.test.ts` (new file, 7 cases)

## Tests executed

- `npx vitest run` — before: 6 files / 66 passed. After: **7 files / 73
  passed** (7 new, 0 modified, 0 removed — existing
  `lifecycleControl.test.ts` untouched).
- `npx tsc --noEmit` — clean before and after.
- `npm run build` (`tsc && vite build`) — clean production build,
  443 modules transformed, no errors.
- Python quality gates (`pytest tests/`, `ruff`, `vulture`) not
  re-run: zero `.py` files in this diff, and both `ruff` and `vulture`
  already exclude `dashboard_src`/`dashboard` per the project's
  standing quality-gate config.

## Known follow-up (found during investigation, NOT in this bundle)

`monitor_open_trades` / `daily_report` are currently failing in this
same production session with `sqlite3.OperationalError: no such
column: execution_lane` against `brain_bot_v13.db`. This is a
different, unrelated, backend/Track A issue — reported separately in
the accompanying chat message, not included in this fix's diff or
commit, per the one-phase-one-commit discipline.
