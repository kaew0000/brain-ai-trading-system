# MIGRATION — Dashboard auth hardening (V16 §81)

## Do you need to do anything?
Rebuild the dashboard so the frontend fixes take effect; no config, schema, dependency or data change.

    cd dashboard_src && npm ci && npm run build

then restart the backend (the launchers auto-build when `dashboard_src/dist` is missing). Hard-refresh the browser
(Ctrl+F5) so the old `WorldPage-*.js` / `index-*.js` bundles are not served from cache.

## Behaviour changes
- `/api/world/*` and `/api/workspace/*` REST calls from the dashboard now carry the Bearer token.
- Dashboard polling starts after the first sign-in attempt settles instead of immediately.
- A malformed (non-ASCII / non-string) API key now gets 401, previously 500.

## Credentials
Nothing changes. If you ever pasted `API_KEYS` / `JWT_SECRET` values into a shared place, rotate them:
`python -c "import secrets;print(secrets.token_hex(32))"` for `JWT_SECRET`,
`python -c "import secrets;print(secrets.token_urlsafe(32))"` for a key in `API_KEYS`, then restart.

## Rollback
`git revert` the single commit. Nothing persisted.
