"""
tests/test_dashboard_serving.py — V16 Track W14-1 Item 9

Regression coverage for the real root cause found during this item:
api/app.py was looking for the V16 Vite build at dashboard/dist/, but
`npm run build` in dashboard_src/ (vite.config.ts's default outDir)
writes to dashboard_src/dist/ — two different directories. That meant
production always silently fell back to the legacy V13 fake-data demo
at dashboard/index.html, build or no build.
"""
from __future__ import annotations

import os
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture()
def client():
    from api.app import app
    return TestClient(app, raise_server_exceptions=False)


class TestDashboardBuildPathResolution:
    def test_dist_points_at_dashboard_src_not_legacy_dashboard_dir(self):
        from api.app import _DASHBOARD_DIST, _DASHBOARD_SRC_DIST
        assert _DASHBOARD_DIST == _DASHBOARD_SRC_DIST
        assert _DASHBOARD_DIST.endswith(os.path.join("dashboard_src", "dist"))
        assert "dashboard" + os.sep + "dist" not in _DASHBOARD_DIST.replace(
            "dashboard_src", ""
        )

    def test_real_v16_build_exists_at_the_resolved_path(self):
        # This is the actual regression check: if this ever goes back to
        # pointing at a directory nothing builds into, this test fails
        # immediately rather than the gap being rediscovered by another
        # audit. Requires `npm run build` to have been run in
        # dashboard_src/ — same precondition Item 1's build-fix tests
        # already assume.
        from api.app import _DASHBOARD_SRC_DIST
        index = os.path.join(_DASHBOARD_SRC_DIST, "index.html")
        assert os.path.exists(index), (
            f"Expected a real V16 build at {index} — run "
            "`npm run build` in dashboard_src/."
        )


class TestDashboardServing:
    def test_root_serves_the_real_v16_build_when_present(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert "V16" in r.text
        assert "BRAIN BOT V13" not in r.text  # legacy demo's own header text

    def test_spa_routes_all_serve_the_same_v16_index(self, client):
        for path in ("/dashboard", "/portfolio", "/world", "/commander"):
            r = client.get(path)
            assert r.status_code == 200
            assert "V16" in r.text

    def test_falls_back_to_legacy_demo_only_when_build_truly_missing(self, monkeypatch):
        import api.app as app_module
        # Point the resolved dist path at a directory that doesn't exist,
        # without touching the real build on disk.
        monkeypatch.setattr(app_module, "_DASHBOARD_DIST", "/nonexistent/build/path")
        with TestClient(app_module.app, raise_server_exceptions=False) as c:
            r = c.get("/")
        assert r.status_code == 200
        assert "BRAIN BOT V13" in r.text  # legacy demo did serve — expected in this case

    def test_legacy_fallback_logs_critical_not_silent(self, monkeypatch, caplog):
        import logging
        import api.app as app_module
        monkeypatch.setattr(app_module, "_DASHBOARD_DIST", "/nonexistent/build/path")
        with caplog.at_level(logging.CRITICAL, logger="api.app"):
            with TestClient(app_module.app, raise_server_exceptions=False) as c:
                c.get("/")
        assert any("LEGACY V13 demo" in rec.message for rec in caplog.records)
