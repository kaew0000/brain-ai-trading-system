import sys
import os

# Add project root to path so all imports resolve
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pytest


@pytest.fixture(autouse=True)
def _default_auth_disabled_for_tests():
    """
    V16 BUG-LIVE-RISK-01: config/settings.py's API_AUTH_ENABLED now
    defaults to True in production code, so a fresh live deployment is
    secure without extra config. The existing test suite predates that
    change and largely assumes auth is off unless a test explicitly turns
    it on (tests/test_api_auth.py's own `auth_client` fixture already
    saves/restores this exact setting around itself for the tests that DO
    want auth on). Rather than touch every test file across the suite
    that builds an unauthenticated TestClient, this autouse fixture
    restores the OLD test-time default (False) for the duration of every
    test, and yields it back afterward. Because both this fixture and
    auth_client() do a proper save-then-restore, they compose correctly
    regardless of pytest's fixture setup/teardown ordering.
    """
    from config.settings import settings
    orig = settings.API_AUTH_ENABLED
    settings.API_AUTH_ENABLED = False
    yield
    settings.API_AUTH_ENABLED = orig
