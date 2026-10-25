# PATCH NOTES — Dashboard auth hardening (V16 §81)

Branch: `feature/dashboard-auth-hardening`
Base: `main` @ `3214105` (PR #119 merged)
Commit: `feat(dashboard): Dashboard auth hardening (V16 §81)` (exactly one)

## Root cause
With `API_AUTH_ENABLED=true` (default), verified in code:
1. `pages/world/api.ts` / `workspaceApi.ts` called bare `fetch()` with no `Authorization` header, so `/api/world/*` and
   `/api/workspace/*` always returned 401, even when signed in. WorldPage's room hydration failed, no room was selected,
   and the scene stayed empty (the room list shown came from `/ws/world`, which authenticates separately).
2. Child effects run before the parent's: `usePoll` and WorldPage fired before `Layout`'s `restoreSession()` completed,
   giving one guaranteed 401 per endpoint on every page load (and no retry for WorldPage's one-shot call).
3. `api/auth.py::_lookup_api_key` used `hmac.compare_digest(str, str)`, which raises `TypeError` for non-ASCII input,
   so a malformed key returned HTTP 500 instead of 401.

## Files
- Backend: `api/auth.py` (bytes compare, reject non-string keys), `tests/test_api_auth.py` (+`TestMalformedApiKeyInput`, 10 cases).
- Frontend: `lib/api.ts` (+`getAuthHeaders`, +`whenAuthSettled`, settle in `login`/`restoreSession`), `hooks/useData.ts`
  (`usePoll` waits and is exported), `pages/world/api.ts`, `pages/world/workspaceApi.ts`, `pages/world/WorldPage.tsx` (`.catch`).
- Tests: new `lib/tests/api.authSettled.test.ts`, `hooks/usePoll.test.tsx`; updated `world.test.ts`, `workspace.test.ts`.
- Docs: `docs/architecture.md` §81, `CHANGELOG.md`, this file, `MIGRATION.md`.

## Verification (actually executed)
`ruff check .` clean; `pytest tests/` 3442 passed / 0 failed; `npx tsc --noEmit` clean; `npx vitest run` 137/137;
`npm run build` ok. New tests were confirmed to FAIL against the old code (7 backend, 15+2 frontend).
Baseline before the change: 3 failures in `tests/test_dashboard_serving.py` caused only by a missing `dashboard_src/dist`
(not committed); they pass once the dashboard is built.

## Impact
No route, schema, setting or public API change. Valid credentials behave as before. Malformed keys: 500 -> 401.

## Limitations / follow-up
- First poll after load can be delayed up to 1.5 s only if no sign-in attempt ever runs (fallback); normally it starts right
  after `restoreSession()` settles.
- Unauthenticated sessions still poll and receive 401 every interval (unchanged); a global "session required" state that
  stops polling and opens the login modal is a separate follow-up.
- Cookie `Secure` flag with non-localhost HTTP origins was noted but not investigated.
