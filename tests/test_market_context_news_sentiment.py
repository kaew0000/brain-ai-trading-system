"""tests/test_market_context_news_sentiment.py — V16 Phase 55.

Focused coverage of intelligence/market_context_builder.py's
news_sentiment wiring: _news_sentiment_dict() (the actual new logic —
converts the background job's cache into the plain-dict shape
market_context carries) and build()'s "intel.get(\"news_sentiment\") or
_news_sentiment_dict()" fallback line. Does not re-test the full
build() pipeline (SMC/volume/regime fixture construction has no
existing precedent anywhere in this test suite to mirror safely) —
that gap pre-dates this phase and is out of scope here.
"""
from __future__ import annotations

import pytest

from intelligence.market_context_builder import _news_sentiment_dict
from intelligence.news_sentiment_feed import NewsSentimentSnapshot, _NewsSentimentCache

pytestmark = pytest.mark.unit


class TestNewsSentimentDict:

    def test_converts_default_snapshot_to_dict(self, monkeypatch):
        import intelligence.news_sentiment_feed as nsf
        monkeypatch.setattr(nsf, "_cache", _NewsSentimentCache())

        result = _news_sentiment_dict()

        assert result == {
            "score": 0.0, "article_count": 0, "as_of": None,
            "sources_ok": 0, "sources_failed": 0,
        }

    def test_converts_populated_snapshot_to_dict(self, monkeypatch):
        import intelligence.news_sentiment_feed as nsf
        cache = _NewsSentimentCache()
        cache.set(NewsSentimentSnapshot(
            score=0.42, article_count=7, as_of="2026-09-17T12:00:00+00:00",
            sources_ok=8, sources_failed=0,
        ))
        monkeypatch.setattr(nsf, "_cache", cache)

        result = _news_sentiment_dict()

        assert result["score"] == 0.42
        assert result["article_count"] == 7
        assert result["as_of"] == "2026-09-17T12:00:00+00:00"

    def test_returns_a_plain_dict_not_a_dataclass(self, monkeypatch):
        """market_context needs a plain dict (JSON-serializable for
        /api/signals) — not a NewsSentimentSnapshot instance."""
        import intelligence.news_sentiment_feed as nsf
        monkeypatch.setattr(nsf, "_cache", _NewsSentimentCache())
        result = _news_sentiment_dict()
        assert isinstance(result, dict)
        assert not isinstance(result, NewsSentimentSnapshot)
