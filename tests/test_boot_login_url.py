"""tests/test_boot_login_url.py — console/log-based dashboard auto-login.

Covers main.py::_boot_login_url(), the companion to the frontend's
boot-token effect in components/layout/Layout.tsx. See main.py's
docstring on _boot_login_url() for the full design and security note.
"""
from __future__ import annotations

import pytest

from config.settings import settings
from main import _boot_login_url

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _restore_settings():
    """Settings is a shared singleton — snapshot/restore the fields
    this test touches so we never leak state into other test modules
    (this repo's own tmp_path-isolation convention, applied to a
    singleton instead of a DB file)."""
    orig_enabled = settings.API_AUTH_ENABLED
    orig_keys = dict(settings.API_KEYS)
    yield
    settings.API_AUTH_ENABLED = orig_enabled
    settings.API_KEYS = orig_keys


class TestBootLoginUrl:
    def test_no_token_when_auth_disabled(self):
        settings.API_AUTH_ENABLED = False
        settings.API_KEYS = {"somekey": "operator"}
        assert _boot_login_url(8000) == "http://localhost:8000/"

    def test_no_token_when_no_keys_configured(self):
        settings.API_AUTH_ENABLED = True
        settings.API_KEYS = {}
        assert _boot_login_url(8000) == "http://localhost:8000/"

    def test_token_present_when_auth_enabled_with_keys(self):
        settings.API_AUTH_ENABLED = True
        settings.API_KEYS = {"abc123": "operator"}
        url = _boot_login_url(8000)
        assert url == "http://localhost:8000/?token=abc123"

    def test_highest_privilege_key_is_chosen(self):
        settings.API_AUTH_ENABLED = True
        settings.API_KEYS = {
            "viewer-key": "viewer",
            "admin-key": "admin",
            "operator-key": "operator",
        }
        url = _boot_login_url(8000)
        assert url == "http://localhost:8000/?token=admin-key"

    def test_unknown_role_names_are_skipped_not_fatal(self):
        settings.API_AUTH_ENABLED = True
        settings.API_KEYS = {"weird-key": "not-a-real-role", "ok-key": "viewer"}
        url = _boot_login_url(8000)
        assert url == "http://localhost:8000/?token=ok-key"

    def test_all_unknown_roles_falls_back_to_plain_url(self):
        settings.API_AUTH_ENABLED = True
        settings.API_KEYS = {"weird-key": "not-a-real-role"}
        assert _boot_login_url(8000) == "http://localhost:8000/"
