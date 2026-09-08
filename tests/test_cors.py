"""tests/test_cors.py — V16 §59: CORS_ALLOWED_ORIGINS.

Was allow_origins=["*"] (flagged "CORS wide open" in
reports/SECURITY_AUDIT.md / docs/V16_AUDIT_REPORT.md), never tested.
This file locks in the new deny-by-default behavior and proves the
settings -> middleware wiring is correct.
"""
from __future__ import annotations

import pytest
from starlette.applications import Starlette
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient

from config.settings import settings

pytestmark = pytest.mark.unit


class TestCorsAllowedOriginsSetting:

    def test_default_is_empty_deny_by_default(self):
        assert settings.CORS_ALLOWED_ORIGINS == []

    def test_parses_a_json_array_from_env(self, monkeypatch):
        from config.settings import Settings
        monkeypatch.setenv("CORS_ALLOWED_ORIGINS", '["https://mydash.example.com"]')
        s = Settings()
        assert s.CORS_ALLOWED_ORIGINS == ["https://mydash.example.com"]


class TestRealAppCorsWiring:
    """Confirms api/app.py's real, already-constructed FastAPI app has
    CORSMiddleware wired to settings.CORS_ALLOWED_ORIGINS rather than a
    hardcoded "*" -- doesn't reconstruct the app (middleware is fixed at
    module-import time), so this only proves the wiring, not the
    allow-listed-origin case (see TestCorsMiddlewareBehavior for that,
    against an isolated instance)."""

    def test_cors_middleware_uses_settings_not_wildcard(self):
        from api.app import app
        cors_entries = [m for m in app.user_middleware if m.cls is CORSMiddleware]
        assert len(cors_entries) == 1
        kwargs = cors_entries[0].kwargs
        assert kwargs["allow_origins"] == settings.CORS_ALLOWED_ORIGINS
        assert kwargs["allow_origins"] != ["*"]

    def test_default_deny_blocks_an_arbitrary_origin_end_to_end(self):
        """Empirical, against the real app: a GET from an arbitrary
        origin still succeeds server-side (this isn't auth), but gets
        no Access-Control-Allow-Origin header -- a browser would refuse
        to let that origin's JS read the response."""
        from api.app import app
        with TestClient(app, raise_server_exceptions=False) as c:
            r = c.get("/api/health", headers={"Origin": "https://evil.example.com"})
        assert r.status_code == 200
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


class TestCorsMiddlewareBehavior:
    """Isolated Starlette app + CORSMiddleware, configured the same way
    api/app.py configures it -- pins the two behaviors §59's fix
    depends on: an empty allowlist rejects every origin, and a
    populated one correctly allows exactly the listed origin(s) and
    nothing else. Standard-library behavior, but nothing in this repo
    pinned it before this file."""

    def _app(self, allow_origins):
        async def ok(request):
            return JSONResponse({"ok": True})

        a = Starlette(routes=[Route("/ping", ok)])
        a.add_middleware(CORSMiddleware, allow_origins=allow_origins,
                          allow_methods=["*"], allow_headers=["*"])
        return a

    def test_empty_allowlist_rejects_every_origin(self):
        with TestClient(self._app([])) as c:
            r = c.get("/ping", headers={"Origin": "https://anything.example.com"})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}

    def test_populated_allowlist_allows_the_listed_origin(self):
        with TestClient(self._app(["https://mydash.example.com"])) as c:
            r = c.get("/ping", headers={"Origin": "https://mydash.example.com"})
        assert r.headers.get("access-control-allow-origin") == "https://mydash.example.com"

    def test_populated_allowlist_still_rejects_an_unlisted_origin(self):
        with TestClient(self._app(["https://mydash.example.com"])) as c:
            r = c.get("/ping", headers={"Origin": "https://evil.example.com"})
        assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}
