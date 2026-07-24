"""
intelligence/market_intelligence_service.py
==============================================
Market Intelligence Feed (v14 Phase 2.5)

Unifies five intelligence sources behind one endpoint (GET /api/intelligence):

  1. funding             — reused from FuturesIntelEngine (already computed
                            every trading cycle, zero new computation)
  2. open_interest        — reused from FuturesIntelEngine
  3. liquidations          — reused from FuturesIntelEngine
  4. fear_greed             — NEW: fetched from a pluggable provider
  5. economic_calendar       — NEW: fetched from a pluggable provider

Design philosophy
------------------
funding/open_interest/liquidations are PURE reads from the market_context
dict that MarketContextBuilder already produces every cycle — this service
adds zero new network calls or computation for those three.

fear_greed and economic_calendar require external data the bot doesn't
already fetch. Both are implemented via an injectable Provider interface
so:
  - Production gets a real HTTP-backed default implementation
  - Tests inject a fake provider — NO live network calls in the test suite
  - A user can swap in their own provider (e.g. a paid econ-calendar API)
    without touching this service's aggregation logic

economic_calendar has no reliable free public API; the default provider
returns an empty list with available=False and a clear note, rather than
fabricating data. This is documented as an extension point.

Usage
-----
from intelligence.market_intelligence_service import MarketIntelligenceService

service = MarketIntelligenceService()
result = service.get_all(market_context)   # market_context = _state["latest_context"]
"""

from __future__ import annotations

import time
from typing import Protocol

from utils.logger import get_logger

logger = get_logger(__name__)

_FEAR_GREED_URL   = "https://api.alternative.me/fng/?limit=1&format=json"
_FEAR_GREED_TTL_S = 600   # cache for 10 minutes — index updates once/day anyway


# ─────────────────────────────────────────────────────────────────────────────
# Provider interfaces (Protocol — duck-typed, easy to fake in tests)
# ─────────────────────────────────────────────────────────────────────────────

class FearGreedProviderProtocol(Protocol):
    def fetch(self) -> dict: ...


class EconomicCalendarProviderProtocol(Protocol):
    def fetch(self) -> list: ...


# ─────────────────────────────────────────────────────────────────────────────
# Default providers
# ─────────────────────────────────────────────────────────────────────────────

class FearGreedProvider:
    """
    Default Fear & Greed Index provider — fetches from alternative.me's
    free public API (no API key required).

    Returns {"value": int, "classification": str, "timestamp": str,
             "available": bool}. On any network failure, returns
    available=False rather than raising — callers should never crash
    the dashboard because an external index is temporarily unreachable.
    """

    def fetch(self) -> dict:
        try:
            import requests
            resp = requests.get(_FEAR_GREED_URL, timeout=5)
            resp.raise_for_status()
            payload = resp.json()
            entry = payload["data"][0]
            return {
                "value":          int(entry["value"]),
                "classification": entry["value_classification"],
                "timestamp":      entry.get("timestamp", ""),
                "available":      True,
            }
        except Exception as exc:
            logger.debug(f"FearGreedProvider fetch failed: {exc}")
            return {
                "value": None, "classification": "", "timestamp": "",
                "available": False, "error": str(exc),
            }


class EconomicCalendarProvider:
    """
    Default Economic Calendar provider — STUB.

    There is no reliable free public economic-calendar API without an API
    key. Rather than fabricate data, this returns an empty, clearly-marked
    "not configured" response. To enable real data, implement a provider
    matching EconomicCalendarProviderProtocol (a `.fetch() -> list` method)
    backed by a paid service (e.g. TradingEconomics, Finnhub) and pass it
    to MarketIntelligenceService(econ_calendar_provider=...).
    """

    def fetch(self) -> list:
        return []


# ─────────────────────────────────────────────────────────────────────────────
# Service
# ─────────────────────────────────────────────────────────────────────────────

class MarketIntelligenceService:
    """
    Aggregates funding/OI/liquidations (from market_context) with
    fear_greed and economic_calendar (from injectable providers) into
    one unified payload for GET /api/intelligence.
    """

    def __init__(
        self,
        fear_greed_provider:  FearGreedProviderProtocol | None       = None,
        econ_calendar_provider: EconomicCalendarProviderProtocol | None = None,
    ) -> None:
        self._fg_provider = fear_greed_provider or FearGreedProvider()
        self._ec_provider = econ_calendar_provider or EconomicCalendarProvider()
        self._fg_cache: dict | None = None
        self._fg_cache_at: float = 0.0

    # ── Individual sources (each independently callable/testable) ────────────

    def get_funding(self, market_context: dict) -> dict:
        """Pure read from market_context['futures']['funding']."""
        futures = (market_context or {}).get("futures", {})
        return futures.get("funding", {
            "rate": 0.0, "annualised": 0.0, "extreme": False, "bias": "NEUTRAL",
        })

    def get_open_interest(self, market_context: dict) -> dict:
        """Pure read from market_context['futures']['open_interest']."""
        futures = (market_context or {}).get("futures", {})
        return futures.get("open_interest", {
            "delta_pct": 0.0, "trend": "FLAT", "pressure": "NEUTRAL",
        })

    def get_liquidations(self, market_context: dict) -> dict:
        """Pure read from market_context['futures']['liquidation']."""
        futures = (market_context or {}).get("futures", {})
        return futures.get("liquidation", {
            "detected": False, "type": "", "severity": "LOW",
        })

    def get_fear_greed(self, force_refresh: bool = False) -> dict:
        """
        Fear & Greed Index, cached for _FEAR_GREED_TTL_S seconds to avoid
        hammering the external API on every dashboard poll.
        """
        now = time.monotonic()
        if (not force_refresh) and self._fg_cache is not None \
                and (now - self._fg_cache_at) < _FEAR_GREED_TTL_S:
            return self._fg_cache

        result = self._fg_provider.fetch()
        self._fg_cache = result
        self._fg_cache_at = now
        return result

    def get_economic_calendar(self) -> dict:
        """List of upcoming economic events, or empty + available=False stub."""
        events = self._ec_provider.fetch()
        return {
            "events":    events,
            "available": len(events) > 0,
        }

    # ── Unified aggregate ──────────────────────────────────────────────────

    def get_all(self, market_context: dict) -> dict:
        """
        Return the unified 5-source payload for GET /api/intelligence.

        funding/open_interest/liquidations always succeed (pure reads with
        safe defaults). fear_greed/economic_calendar each degrade
        gracefully to available=False on failure — this method never
        raises.
        """
        return {
            "funding":           self.get_funding(market_context),
            "open_interest":     self.get_open_interest(market_context),
            "liquidations":      self.get_liquidations(market_context),
            "fear_greed":        self.get_fear_greed(),
            "economic_calendar": self.get_economic_calendar(),
        }


# ── Singleton accessor (mirrors telemetry/reasoning pattern) ──────────────────

_global_service: MarketIntelligenceService | None = None


def get_market_intelligence_service() -> MarketIntelligenceService:
    global _global_service
    if _global_service is None:
        _global_service = MarketIntelligenceService()
        logger.info("MarketIntelligenceService ready")
    return _global_service


def reset_market_intelligence_service(
    fear_greed_provider: FearGreedProviderProtocol | None = None,
    econ_calendar_provider: EconomicCalendarProviderProtocol | None = None,
) -> MarketIntelligenceService:
    """Replace the global singleton (useful in tests to inject fakes)."""
    global _global_service
    _global_service = MarketIntelligenceService(
        fear_greed_provider=fear_greed_provider,
        econ_calendar_provider=econ_calendar_provider,
    )
    return _global_service
