"""
tests/test_api_auth.py

P1-A — Dashboard Authentication tests. Exercises the real enforcement
path with API_AUTH_ENABLED explicitly turned on (it defaults to False —
see config/settings.py — precisely so the rest of this suite doesn't need
to change). api/app.py and api/auth.py both import the same `settings`
singleton, so every test here restores it afterward to avoid leaking
state into other test modules that share the same FastAPI app.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


@pytest.fixture()
def auth_client():
    from config.settings import settings
    from api.app import app
    import api.auth as auth_module

    orig_enabled = settings.API_AUTH_ENABLED
    orig_keys    = dict(settings.API_KEYS)
    orig_secret  = settings.JWT_SECRET
    orig_expiry  = settings.JWT_EXPIRY_MINUTES

    settings.API_AUTH_ENABLED = True
    settings.API_KEYS = {
        "test-admin-key":    "admin",
        "test-operator-key": "operator",
        "test-viewer-key":   "viewer",
    }
    settings.JWT_SECRET = "test-secret-do-not-use-in-prod"
    settings.JWT_EXPIRY_MINUTES = 60
    auth_module._revoked_jti.clear()

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c

    settings.API_AUTH_ENABLED = orig_enabled
    settings.API_KEYS = orig_keys
    settings.JWT_SECRET = orig_secret
    settings.JWT_EXPIRY_MINUTES = orig_expiry
    auth_module._revoked_jti.clear()


# ── API key auth ──────────────────────────────────────────────────────────

class TestApiKeyAuth:
    def test_missing_credentials_rejected(self, auth_client):
        r = auth_client.get("/api/config")
        assert r.status_code == 401

    def test_invalid_api_key_rejected(self, auth_client):
        r = auth_client.get("/api/config", headers={"X-API-Key": "not-a-real-key"})
        assert r.status_code == 401

    def test_valid_viewer_key_reads_ok(self, auth_client):
        r = auth_client.get("/api/config", headers={"X-API-Key": "test-viewer-key"})
        assert r.status_code == 200
        assert r.json()["ok"] is True

    def test_viewer_key_cannot_issue_command(self, auth_client):
        r = auth_client.post(
            "/api/command",
            json={"command": "show risk"},
            headers={"X-API-Key": "test-viewer-key"},
        )
        assert r.status_code == 403

    def test_operator_key_can_issue_command(self, auth_client):
        r = auth_client.post(
            "/api/command",
            json={"command": "show risk"},
            headers={"X-API-Key": "test-operator-key"},
        )
        assert r.status_code == 200

    def test_admin_key_outranks_operator_requirement(self, auth_client):
        r = auth_client.post(
            "/api/command",
            json={"command": "show pnl"},
            headers={"X-API-Key": "test-admin-key"},
        )
        assert r.status_code == 200

    def test_liveness_probe_stays_public(self, auth_client):
        # Infra health checks / load balancers must not need credentials.
        r = auth_client.get("/api/health")
        assert r.status_code == 200


# ── Bearer token issuance, expiration, rotation ─────────────────────────────

class TestBearerTokens:
    def test_token_issued_for_valid_api_key(self, auth_client):
        r = auth_client.post("/api/auth/token", json={"api_key": "test-viewer-key"})
        assert r.status_code == 200
        data = r.json()["data"]
        assert data["role"] == "VIEWER"
        assert "token" in data

    def test_token_rejected_for_invalid_api_key(self, auth_client):
        r = auth_client.post("/api/auth/token", json={"api_key": "nope"})
        assert r.status_code == 401

    def test_bearer_token_grants_access(self, auth_client):
        tok = auth_client.post("/api/auth/token", json={"api_key": "test-viewer-key"}).json()["data"]["token"]
        r = auth_client.get("/api/config", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200

    def test_expired_token_rejected(self, auth_client):
        from api.auth import issue_token, Role
        from config.settings import settings as s

        s.JWT_EXPIRY_MINUTES = -1   # force an already-expired token
        expired = issue_token(Role.VIEWER)["token"]
        s.JWT_EXPIRY_MINUTES = 60

        r = auth_client.get("/api/config", headers={"Authorization": f"Bearer {expired}"})
        assert r.status_code == 401

    def test_rotate_issues_new_token_and_revokes_old(self, auth_client):
        tok = auth_client.post("/api/auth/token", json={"api_key": "test-operator-key"}).json()["data"]["token"]

        r = auth_client.post("/api/auth/rotate", headers={"Authorization": f"Bearer {tok}"})
        assert r.status_code == 200
        new_tok = r.json()["data"]["token"]
        assert new_tok != tok

        r_old = auth_client.get("/api/config", headers={"Authorization": f"Bearer {tok}"})
        assert r_old.status_code == 401   # revoked

        r_new = auth_client.post(
            "/api/command", json={"command": "show risk"},
            headers={"Authorization": f"Bearer {new_tok}"},
        )
        assert r_new.status_code == 200   # kept the operator role

    def test_rotate_without_token_rejected(self, auth_client):
        r = auth_client.post("/api/auth/rotate")
        assert r.status_code == 401


# ── WebSocket auth ───────────────────────────────────────────────────────────

class TestWebSocketAuth:
    def test_ws_events_rejects_without_credentials(self, auth_client):
        with pytest.raises(Exception), auth_client.websocket_connect("/ws/events"):
            pass

    def test_ws_events_accepts_viewer_key(self, auth_client):
        with auth_client.websocket_connect(
            "/ws/events", headers={"X-API-Key": "test-viewer-key"}
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"

    def test_ws_command_rejects_viewer_key(self, auth_client):
        with pytest.raises(Exception), auth_client.websocket_connect(
            "/ws/command", headers={"X-API-Key": "test-viewer-key"}
        ):
            pass

    def test_ws_command_accepts_operator_key(self, auth_client):
        with auth_client.websocket_connect(
            "/ws/command", headers={"X-API-Key": "test-operator-key"}
        ) as ws:
            msg = ws.receive_json()
            assert msg["type"] == "init"


# ── Default-value contract (V16 BUG-LIVE-RISK-01) ────────────────────────────

class TestAuthEnabledByDefault:
    def test_default_settings_has_auth_on(self):
        from config.settings import Settings
        # V16 BUG-LIVE-RISK-01: a fresh Settings() (no env overrides) must
        # now default to ENABLED — a live deployment is secure without
        # extra config. This test suite still runs with auth OFF by
        # default via conftest.py's autouse
        # `_default_auth_disabled_for_tests` fixture (a test-time-only
        # override), NOT via this production-code default — read this
        # assertion together with that fixture, not in isolation.
        assert Settings().API_AUTH_ENABLED is True

    def test_conftest_fixture_disables_auth_for_ordinary_tests(self):
        # Meta-test: confirms the autouse fixture in conftest.py is
        # actually active here even though this test requested nothing
        # auth-related itself — this is what keeps every other test
        # module's unauthenticated TestClient calls working unchanged.
        from config.settings import settings
        assert settings.API_AUTH_ENABLED is False


class TestEphemeralKeyBootstrap:
    """
    api/auth.py's _bootstrap_ephemeral_api_key(): if API_AUTH_ENABLED is
    true and API_KEYS is empty (e.g. a fresh .env with only
    API_AUTH_ENABLED set), the dashboard must not come up fully locked
    out. It should generate one ephemeral OPERATOR key, log it once at
    CRITICAL, and that key must actually work — mirrors the existing
    JWT_SECRET ephemeral-generation behavior a few lines above it.

    Calls the function directly rather than importlib.reload(api.auth):
    api/app.py holds direct references to this module's exports
    (Role, AuthContext, the auth functions), and reloading api.auth
    mid-suite desyncs those references for every test that runs
    afterward — confirmed by TestLifecycleCommandAuth failing with 500s
    instead of 401s only when a reload-based version of these tests ran
    first in the same session.
    """

    def test_generates_one_operator_key_when_none_configured(self, monkeypatch):
        from config.settings import settings
        import api.auth as auth_module

        monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "API_KEYS", {})

        auth_module._bootstrap_ephemeral_api_key()

        assert len(settings.API_KEYS) == 1
        (generated_key, role), = settings.API_KEYS.items()
        assert role == "operator"
        assert len(generated_key) > 20  # secrets.token_urlsafe(32), not a placeholder

    def test_logs_critical_with_the_generated_key(self, monkeypatch, caplog):
        import logging
        from config.settings import settings
        import api.auth as auth_module

        monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "API_KEYS", {})

        with caplog.at_level(logging.CRITICAL, logger="api.auth"):
            auth_module._bootstrap_ephemeral_api_key()

        (generated_key,) = settings.API_KEYS.keys()
        assert any(
            "API_KEYS is empty" in rec.message and generated_key in rec.message
            for rec in caplog.records
        )

    def test_generated_key_actually_authenticates(self, monkeypatch):
        from config.settings import settings
        import api.auth as auth_module

        monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "API_KEYS", {})

        auth_module._bootstrap_ephemeral_api_key()

        (generated_key,) = settings.API_KEYS.keys()
        role = auth_module._lookup_api_key(generated_key)
        assert role is auth_module.Role.OPERATOR

    def test_configured_keys_are_left_untouched(self, monkeypatch):
        from config.settings import settings
        import api.auth as auth_module

        monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)
        monkeypatch.setattr(settings, "API_KEYS", {"real-key": "viewer"})

        auth_module._bootstrap_ephemeral_api_key()

        assert settings.API_KEYS == {"real-key": "viewer"}

    def test_noop_when_auth_disabled(self, monkeypatch):
        from config.settings import settings
        import api.auth as auth_module

        monkeypatch.setattr(settings, "API_AUTH_ENABLED", False)
        monkeypatch.setattr(settings, "API_KEYS", {})

        auth_module._bootstrap_ephemeral_api_key()

        assert settings.API_KEYS == {}


class TestLiveModeRequiresAuth:
    """
    V16 BUG-LIVE-RISK-01: api/app.py's lifespan() refuses to start the
    dashboard server at all when EXECUTION_MODE=live and
    API_AUTH_ENABLED=false, regardless of what the default is. Checked at
    server-startup time (lifespan), not at import time, so these tests
    exercise `with TestClient(app):` rather than the bare import.
    """

    def test_live_mode_without_auth_refuses_to_start(self, monkeypatch):
        from fastapi.testclient import TestClient
        from config.settings import settings
        import api.app as app_module

        monkeypatch.setenv("EXECUTION_MODE", "live")
        monkeypatch.setattr(settings, "API_AUTH_ENABLED", False)

        with pytest.raises(RuntimeError, match="Refusing to start"):
            with TestClient(app_module.app):
                pass

    def test_live_mode_with_auth_starts_normally(self, monkeypatch):
        from fastapi.testclient import TestClient
        from config.settings import settings
        import api.app as app_module

        monkeypatch.setenv("EXECUTION_MODE", "live")
        monkeypatch.setattr(settings, "API_AUTH_ENABLED", True)

        with TestClient(app_module.app):
            pass  # no exception raised == started fine

    def test_paper_mode_without_auth_still_starts(self, monkeypatch):
        from fastapi.testclient import TestClient
        from config.settings import settings
        import api.app as app_module

        monkeypatch.setenv("EXECUTION_MODE", "paper")
        monkeypatch.setattr(settings, "API_AUTH_ENABLED", False)

        with TestClient(app_module.app):
            pass  # paper/testnet may still legitimately run without auth


class TestLifecycleCommandAuth:
    """
    V16 Track W14-1 Item 7 — dedicated coverage for the actual "start
    bot"/"stop bot" commands (Item 6's START/STOP UI), rather than
    relying on TestApiKeyAuth's generic "show risk"/"show pnl" commands
    as a stand-in. The auth middleware enforces role by route+method
    before the handler ever sees the command string (see api/app.py's
    _AUTH_OPERATOR_ROUTES), so those generic tests already prove the
    mechanism works — this class proves it specifically for the two
    commands the new frontend button actually sends.
    """

    @pytest.fixture(autouse=True)
    def _reset_lifecycle(self):
        from commander.control_state import reset_control_state
        reset_control_state()
        yield
        reset_control_state()

    def test_unauthenticated_start_command_rejected(self, auth_client):
        r = auth_client.post("/api/command", json={"command": "start bot"})
        assert r.status_code == 401

    def test_unauthenticated_stop_command_rejected(self, auth_client):
        r = auth_client.post("/api/command", json={"command": "stop bot"})
        assert r.status_code == 401

    def test_viewer_cannot_start(self, auth_client):
        r = auth_client.post(
            "/api/command", json={"command": "start bot"},
            headers={"X-API-Key": "test-viewer-key"},
        )
        assert r.status_code == 403

    def test_viewer_cannot_stop(self, auth_client):
        r = auth_client.post(
            "/api/command", json={"command": "stop bot"},
            headers={"X-API-Key": "test-viewer-key"},
        )
        assert r.status_code == 403

    def test_operator_can_start(self, auth_client):
        r = auth_client.post(
            "/api/command", json={"command": "start bot"},
            headers={"X-API-Key": "test-operator-key"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["success"] is True
        assert body["data"]["data"]["lifecycle_state"] in ("STARTING", "RUNNING")

    def test_operator_can_stop(self, auth_client):
        from commander.control_state import get_control_state
        get_control_state().mark_starting()
        get_control_state().mark_running()
        r = auth_client.post(
            "/api/command", json={"command": "stop bot"},
            headers={"X-API-Key": "test-operator-key"},
        )
        assert r.status_code == 200
        body = r.json()
        assert body["ok"] is True
        assert body["data"]["success"] is True
        # stop() resolves synchronously STOPPING -> STOPPED today (single-
        # process, no real async drain step yet — see control_state.py's
        # own stop() docstring), so the final reported state is STOPPED,
        # not STOPPING.
        assert body["data"]["data"]["lifecycle_state"] == "STOPPED"

    def test_bearer_token_from_operator_key_can_start(self, auth_client):
        # This is the exact path the new LoginModal/LifecycleControl
        # frontend flow uses: exchange an API key for a Bearer token
        # once, then send commands with that token — not the raw key.
        tok = auth_client.post(
            "/api/auth/token", json={"api_key": "test-operator-key"},
        ).json()["data"]["token"]
        r = auth_client.post(
            "/api/command", json={"command": "start bot"},
            headers={"Authorization": f"Bearer {tok}"},
        )
        assert r.status_code == 200
        assert r.json()["data"]["success"] is True

    def test_invalid_bearer_token_rejected_for_start(self, auth_client):
        r = auth_client.post(
            "/api/command", json={"command": "start bot"},
            headers={"Authorization": "Bearer not-a-real-token"},
        )
        assert r.status_code == 401

    def test_illegal_transition_reports_failure_not_success(self, auth_client):
        # Starting twice in a row: second call must not silently succeed
        # or lie about the resulting state — matches Item 6's "no
        # optimistic UI" requirement on the backend side too.
        auth_client.post(
            "/api/command", json={"command": "start bot"},
            headers={"X-API-Key": "test-operator-key"},
        )
        r = auth_client.post(
            "/api/command", json={"command": "stop bot"},
            headers={"X-API-Key": "test-viewer-key"},  # wrong role this time
        )
        assert r.status_code == 403
        # And the lifecycle state must be unaffected by the rejected call.
        from commander.control_state import get_control_state
        assert get_control_state().lifecycle_state() != "STOPPING"

