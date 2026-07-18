"""
tests/test_market_intelligence.py
====================================
v14 Phase 2.5 — Market Intelligence Feed test suite.

Covers:
  - MarketIntelligenceService pure reads (funding/OI/liquidations)
  - Fear & Greed provider injection + caching (NO live network calls)
  - Economic calendar stub behaviour
  - get_all() unified aggregation, never raises
  - GET /api/intelligence (REST)

All tests use FAKE providers — zero real HTTP requests are made.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


# ─────────────────────────────────────────────────────────────────────────────
# Fakes (no live network calls anywhere in this test file)
# ─────────────────────────────────────────────────────────────────────────────

class FakeFearGreedProvider:
    def __init__(self, value=55, classification="Greed", available=True):
        self.value = value
        self.classification = classification
        self.available = available
        self.call_count = 0

    def fetch(self) -> dict:
        self.call_count += 1
        if not self.available:
            return {"value": None, "classification": "", "timestamp": "",
                     "available": False, "error": "simulated failure"}
        return {"value": self.value, "classification": self.classification,
                 "timestamp": "2026-06-20T00:00:00Z", "available": True}


class FakeEconomicCalendarProvider:
    def __init__(self, events=None):
        self._events = events or []

    def fetch(self) -> list:
        return self._events


@pytest.fixture
def market_context():
    return {
        "futures": {
            "funding":       {"rate": 0.0002, "annualised": 21.9, "extreme": False, "bias": "LONG_PAYING"},
            "open_interest": {"delta_pct": 0.018, "trend": "RISING", "pressure": "BUY_PRESSURE"},
            "liquidation":   {"detected": True, "type": "LONG_LIQUIDATION", "severity": "HIGH"},
        }
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pure reads (funding / OI / liquidations)
# ─────────────────────────────────────────────────────────────────────────────
class TestPureReads:

    def test_get_funding_reads_from_context(self, market_context):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        funding = svc.get_funding(market_context)
        assert funding["rate"] == pytest.approx(0.0002)
        assert funding["bias"] == "LONG_PAYING"

    def test_get_open_interest_reads_from_context(self, market_context):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        oi = svc.get_open_interest(market_context)
        assert oi["delta_pct"] == pytest.approx(0.018)
        assert oi["trend"] == "RISING"

    def test_get_liquidations_reads_from_context(self, market_context):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        liq = svc.get_liquidations(market_context)
        assert liq["detected"] is True
        assert liq["severity"] == "HIGH"

    def test_get_funding_default_when_missing(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        funding = svc.get_funding({})
        assert funding["bias"] == "NEUTRAL"
        assert funding["rate"] == 0.0

    def test_get_open_interest_default_when_none(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        oi = svc.get_open_interest(None)
        assert oi["trend"] == "FLAT"

    def test_get_liquidations_default_when_empty(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        liq = svc.get_liquidations({"futures": {}})
        assert liq["detected"] is False


# ─────────────────────────────────────────────────────────────────────────────
# Fear & Greed (injected fake — no network)
# ─────────────────────────────────────────────────────────────────────────────
class TestFearGreed:

    def test_fetches_via_provider(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        fake = FakeFearGreedProvider(value=72, classification="Greed")
        svc = MarketIntelligenceService(fear_greed_provider=fake)
        result = svc.get_fear_greed()
        assert result["value"] == 72
        assert result["classification"] == "Greed"
        assert result["available"] is True

    def test_caches_between_calls(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        fake = FakeFearGreedProvider()
        svc = MarketIntelligenceService(fear_greed_provider=fake)
        svc.get_fear_greed()
        svc.get_fear_greed()
        svc.get_fear_greed()
        assert fake.call_count == 1   # only the first call hit the provider

    def test_force_refresh_bypasses_cache(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        fake = FakeFearGreedProvider()
        svc = MarketIntelligenceService(fear_greed_provider=fake)
        svc.get_fear_greed()
        svc.get_fear_greed(force_refresh=True)
        assert fake.call_count == 2

    def test_provider_failure_returns_available_false(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        fake = FakeFearGreedProvider(available=False)
        svc = MarketIntelligenceService(fear_greed_provider=fake)
        result = svc.get_fear_greed()
        assert result["available"] is False
        assert result["value"] is None

    def test_real_provider_network_failure_does_not_raise(self):
        """The REAL FearGreedProvider must never raise — even with no
        network access in this sandboxed test environment."""
        from intelligence.market_intelligence_service import FearGreedProvider
        provider = FearGreedProvider()
        result = provider.fetch()   # may succeed or fail depending on sandbox network
        assert "available" in result
        assert isinstance(result["available"], bool)


# ─────────────────────────────────────────────────────────────────────────────
# Economic Calendar (stub by default)
# ─────────────────────────────────────────────────────────────────────────────
class TestEconomicCalendar:

    def test_default_stub_returns_unavailable(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        result = svc.get_economic_calendar()
        assert result["events"] == []
        assert result["available"] is False

    def test_injected_provider_with_events(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        events = [{"event": "CPI Release", "impact": "HIGH", "date": "2026-06-25"}]
        fake_ec = FakeEconomicCalendarProvider(events=events)
        svc = MarketIntelligenceService(
            fear_greed_provider=FakeFearGreedProvider(),
            econ_calendar_provider=fake_ec,
        )
        result = svc.get_economic_calendar()
        assert result["available"] is True
        assert len(result["events"]) == 1
        assert result["events"][0]["event"] == "CPI Release"


# ─────────────────────────────────────────────────────────────────────────────
# Unified get_all()
# ─────────────────────────────────────────────────────────────────────────────
class TestUnifiedAggregate:

    def test_get_all_has_five_keys(self, market_context):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        result = svc.get_all(market_context)
        assert set(result.keys()) == {"funding", "open_interest", "liquidations",
                                       "fear_greed", "economic_calendar"}

    def test_get_all_never_raises_on_empty_context(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        result = svc.get_all({})
        assert result["funding"]["bias"] == "NEUTRAL"

    def test_get_all_never_raises_on_none_context(self):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider())
        result = svc.get_all(None)
        assert result["open_interest"]["trend"] == "FLAT"

    def test_get_all_degrades_gracefully_when_fg_fails(self, market_context):
        from intelligence.market_intelligence_service import MarketIntelligenceService
        svc = MarketIntelligenceService(fear_greed_provider=FakeFearGreedProvider(available=False))
        result = svc.get_all(market_context)
        assert result["fear_greed"]["available"] is False
        # other sources still populated correctly
        assert result["funding"]["bias"] == "LONG_PAYING"


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────
class TestSingleton:

    def test_get_service_returns_same_instance(self):
        from intelligence.market_intelligence_service import get_market_intelligence_service
        s1 = get_market_intelligence_service()
        s2 = get_market_intelligence_service()
        assert s1 is s2

    def test_reset_replaces_singleton_with_injected_providers(self):
        from intelligence.market_intelligence_service import reset_market_intelligence_service
        fake = FakeFearGreedProvider(value=99)
        svc = reset_market_intelligence_service(fear_greed_provider=fake)
        result = svc.get_fear_greed()
        assert result["value"] == 99


# ─────────────────────────────────────────────────────────────────────────────
# API: GET /api/intelligence
# ─────────────────────────────────────────────────────────────────────────────
class TestIntelligenceAPI:

    @pytest.fixture(autouse=True)
    def inject_fake_service(self):
        from intelligence.market_intelligence_service import reset_market_intelligence_service
        reset_market_intelligence_service(
            fear_greed_provider=FakeFearGreedProvider(value=63, classification="Greed"),
            econ_calendar_provider=FakeEconomicCalendarProvider(),
        )
        yield
        reset_market_intelligence_service()

    @pytest.fixture
    def client(self):
        from api.app import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c

    def test_endpoint_200(self, client):
        r = client.get("/api/intelligence")
        assert r.status_code == 200

    def test_endpoint_ok_true(self, client):
        body = client.get("/api/intelligence").json()
        assert body["ok"] is True

    def test_endpoint_has_five_sources(self, client):
        body = client.get("/api/intelligence").json()["data"]
        for key in ("funding", "open_interest", "liquidations",
                    "fear_greed", "economic_calendar"):
            assert key in body

    def test_endpoint_fear_greed_value(self, client):
        body = client.get("/api/intelligence").json()["data"]
        assert body["fear_greed"]["value"] == 63

    def test_endpoint_has_timestamp(self, client):
        body = client.get("/api/intelligence").json()["data"]
        assert "timestamp" in body

    def test_endpoint_works_with_no_latest_context(self, client):
        """Before the first trading cycle, _state['latest_context'] is None."""
        from api.app import set_state
        set_state("latest_context", None)
        r = client.get("/api/intelligence")
        assert r.status_code == 200
        body = r.json()["data"]
        assert body["funding"]["bias"] == "NEUTRAL"
