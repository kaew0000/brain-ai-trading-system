# PATCH NOTES — CORS: Deny by Default (V16 §59)

Branch: `fix/cors-deny-by-default`
Base: `main` @ `95c16e3` (merge of PR #94, nightly retrain governance gate)

## Root cause / gap

`api/app.py`'s `CORSMiddleware` was configured with `allow_origins=
["*"]` — any website's JavaScript could read responses from any
unauthenticated endpoint, and (server reachability permitting) probe
the API cross-origin. Flagged as "CORS wide open" in this project's
own `reports/SECURITY_AUDIT.md` and `docs/V16_AUDIT_REPORT.md`. Never
had any test coverage.

Traced whether any *legitimate* cross-origin browser use actually
depends on this before touching it, per this project's own
"determine whether the fix would break something real" discipline:

- **Production dashboard**: served by this same FastAPI app
  (`api/app.py`'s `/assets` `StaticFiles` mount) — same origin, CORS
  is not involved at all.
- **Dev server** (`dashboard_src/vite.config.ts`): proxies `/api` and
  `/ws` server-side (`changeOrigin: true`) — the browser only ever
  talks to `localhost:5173`, never directly to the FastAPI backend, so
  CORS is not involved there either.
- **Frontend API client** (`dashboard_src/src/lib/api.ts`): `const
  BASE = ''` — every request is a relative URL, always same-origin, in
  every deployment mode. No `VITE_API_URL`-style override exists.
- The one place `credentials: 'include'` is used (the httpOnly refresh
  cookie, V16 Phase 4C) would have needed `allow_credentials=True` on
  the middleware to ever work cross-origin, which was never set
  (defaults `False`) — so even a hypothetical cross-origin client
  could never have completed the credentialed flow anyway.

Conclusion: `allow_origins=["*"]` had zero functional purpose for
anything this project actually does, and was pure attack surface.

## Fix

- `config/settings.py` — new `CORS_ALLOWED_ORIGINS: list[str]`
  (default `[]`, JSON-array-from-env, same pattern as the existing
  `API_KEYS: dict[str, str]` field).
- `api/app.py` — `CORSMiddleware(allow_origins=settings.
  CORS_ALLOWED_ORIGINS, ...)` instead of the hardcoded `["*"]`.
  `allow_methods`/`allow_headers` left as `["*"]` — the flagged issue
  was specifically about origins, and these only matter for a request
  that already passed the origin check.
- `.env.example` — documented commented-out example, matching the
  `API_KEYS` entry's style.

Empty allowlist ≠ broken: a request from a disallowed origin still
executes normally server-side (this is not an auth mechanism), it just
gets no `Access-Control-Allow-Origin` response header, which is what
makes a browser refuse to let that origin's JS read the response.
Confirmed empirically against the real app in this phase's tests.

## Tests

New: `tests/test_cors.py` — 7 tests:
- Settings: default is `[]`; parses a JSON-array env value correctly.
- Real app wiring: `CORSMiddleware` is actually configured from
  `settings.CORS_ALLOWED_ORIGINS`, not a hardcoded `["*"]`; an
  end-to-end request from an arbitrary origin against the real running
  app gets no `Access-Control-Allow-Origin` header.
- Isolated middleware behavior (pins the underlying mechanism, since
  nothing tested it before): empty allowlist rejects every origin;
  populated allowlist allows exactly the listed origin(s); a populated
  allowlist still rejects an unlisted origin.

Full suite: `pytest tests/` → **3053 passed, 4 skipped, 45
deselected**. Same 3 pre-existing `tests/test_dashboard_serving.py`
failures as every phase this week (missing frontend build artifact) —
unrelated, unaffected.

`ruff check .` → all checks passed, repo-wide. `vulture
--min-confidence 80` → clean on every changed file.
`python -c "import main"` → succeeds.

## Files changed

`config/settings.py`, `api/app.py`, `.env.example`,
`tests/test_cors.py` (new), `PATCH_NOTES.md`, `MIGRATION.md`,
`CHANGELOG.md`, `docs/architecture.md` (§59).
