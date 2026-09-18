"""
tests/test_news_sentiment_feed.py — V16 Phase 55.

Covers intelligence/news_sentiment_feed.py: the cache/snapshot shape,
per-source fetch resilience (a failing/malformed feed never raises and
never blocks the others), the lookback-window cutoff, the article cap,
and refresh_news_sentiment()'s end-to-end behavior with settings on/off.
No real network calls — feedparser.parse and the VADER analyzer are
both monkeypatched/stubbed.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from intelligence.news_sentiment_feed import (
    NewsSentimentSnapshot,
    SOURCES,
    _NewsSentimentCache,
    _fetch_one_source,
    get_news_sentiment_snapshot,
    refresh_news_sentiment,
)

pytestmark = pytest.mark.unit


# ══════════════════════════════════════════════════════════════════════════
# NewsSentimentSnapshot / is_stale
# ══════════════════════════════════════════════════════════════════════════

class TestNewsSentimentSnapshot:

    def test_defaults_are_no_data(self):
        snap = NewsSentimentSnapshot()
        assert snap.score == 0.0
        assert snap.article_count == 0
        assert snap.as_of is None

    def test_is_stale_true_when_as_of_none(self):
        snap = NewsSentimentSnapshot()
        assert snap.is_stale(max_age_minutes=30) is True

    def test_is_stale_false_when_recent(self):
        snap = NewsSentimentSnapshot(as_of=datetime.now(timezone.utc).isoformat())
        assert snap.is_stale(max_age_minutes=30) is False

    def test_is_stale_true_when_old(self):
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        snap = NewsSentimentSnapshot(as_of=old)
        assert snap.is_stale(max_age_minutes=30) is True

    def test_is_stale_true_on_malformed_as_of(self):
        snap = NewsSentimentSnapshot(as_of="not-a-timestamp")
        assert snap.is_stale(max_age_minutes=30) is True


# ══════════════════════════════════════════════════════════════════════════
# _NewsSentimentCache / get_news_sentiment_snapshot
# ══════════════════════════════════════════════════════════════════════════

class TestCache:

    def test_new_cache_returns_default_snapshot(self):
        cache = _NewsSentimentCache()
        snap = cache.get()
        assert snap.article_count == 0

    def test_set_then_get_round_trips(self):
        cache = _NewsSentimentCache()
        cache.set(NewsSentimentSnapshot(score=0.5, article_count=10, as_of="2026-09-17T00:00:00+00:00"))
        snap = cache.get()
        assert snap.score == 0.5
        assert snap.article_count == 10

    def test_get_news_sentiment_snapshot_returns_module_singleton(self, monkeypatch):
        """get_news_sentiment_snapshot() is market_context_builder.py's
        read side — must reflect whatever the module-level cache holds."""
        import intelligence.news_sentiment_feed as nsf
        fresh_cache = _NewsSentimentCache()
        fresh_cache.set(NewsSentimentSnapshot(score=0.3, article_count=5, as_of="2026-09-17T00:00:00+00:00"))
        monkeypatch.setattr(nsf, "_cache", fresh_cache)
        snap = get_news_sentiment_snapshot()
        assert snap.score == 0.3
        assert snap.article_count == 5


# ══════════════════════════════════════════════════════════════════════════
# _fetch_one_source
# ══════════════════════════════════════════════════════════════════════════

class _FakeAnalyzer:
    """Stand-in for VADER's SentimentIntensityAnalyzer — deterministic,
    keyword-driven so tests don't depend on VADER's actual lexicon."""
    def polarity_scores(self, text: str) -> dict:
        if "surge" in text.lower() or "rally" in text.lower():
            return {"compound": 0.8}
        if "crash" in text.lower() or "hack" in text.lower():
            return {"compound": -0.8}
        return {"compound": 0.0}


class _FakeEntry:
    def __init__(self, title, published_parsed=None):
        self.title = title
        self.published_parsed = published_parsed


class _FakeParsed:
    def __init__(self, entries, bozo=False, bozo_exception=None):
        self.entries = entries
        self.bozo = bozo
        self.bozo_exception = bozo_exception


def _struct_time(dt: datetime):
    return dt.timetuple()


class TestFetchOneSource:

    def test_scores_in_window_headlines(self, monkeypatch):
        now = datetime.now(timezone.utc)
        entries = [
            _FakeEntry("Bitcoin surges past new high", _struct_time(now)),
            _FakeEntry("Market crash wipes out gains", _struct_time(now)),
        ]
        monkeypatch.setattr(
            "feedparser.parse", lambda url: _FakeParsed(entries)
        )
        cutoff = now - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert ok is True
        assert scores == [0.8, -0.8]

    def test_excludes_headlines_outside_lookback_window(self, monkeypatch):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)
        entries = [
            _FakeEntry("Bitcoin surges past new high", _struct_time(now)),
            _FakeEntry("Old rally news", _struct_time(old)),
        ]
        monkeypatch.setattr("feedparser.parse", lambda url: _FakeParsed(entries))
        cutoff = now - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert scores == [0.8]  # only the recent one

    def test_scores_headline_with_no_published_date_anyway(self, monkeypatch):
        entries = [_FakeEntry("Bitcoin surges", published_parsed=None)]
        monkeypatch.setattr("feedparser.parse", lambda url: _FakeParsed(entries))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert scores == [0.8]

    def test_respects_max_articles_cap(self, monkeypatch):
        now = datetime.now(timezone.utc)
        entries = [_FakeEntry(f"Headline {i}", _struct_time(now)) for i in range(10)]
        monkeypatch.setattr("feedparser.parse", lambda url: _FakeParsed(entries))
        cutoff = now - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=3)
        assert len(scores) == 3

    def test_bozo_feed_returns_not_ok(self, monkeypatch):
        monkeypatch.setattr(
            "feedparser.parse",
            lambda url: _FakeParsed([], bozo=True, bozo_exception="malformed XML"),
        )
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert scores == []
        assert ok is False

    def test_exception_during_fetch_returns_not_ok(self, monkeypatch):
        def _raise(url):
            raise RuntimeError("connection refused")
        monkeypatch.setattr("feedparser.parse", _raise)
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert scores == []
        assert ok is False

    def test_entry_without_title_is_skipped(self, monkeypatch):
        class _NoTitle:
            published_parsed = None
        monkeypatch.setattr("feedparser.parse", lambda url: _FakeParsed([_NoTitle()]))
        cutoff = datetime.now(timezone.utc) - timedelta(hours=6)
        scores, ok = _fetch_one_source("test", "http://x", _FakeAnalyzer(), cutoff, max_articles=30)
        assert scores == []
        assert ok is True  # feed itself was fine, just nothing scorable


# ══════════════════════════════════════════════════════════════════════════
# refresh_news_sentiment()
# ══════════════════════════════════════════════════════════════════════════

class TestRefreshNewsSentiment:

    def test_noop_when_disabled(self, monkeypatch):
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_ENABLED", False)
        result = refresh_news_sentiment()
        assert result == {"sources_ok": 0, "sources_failed": 0, "articles_scored": 0}

    def test_averages_scores_across_all_sources(self, monkeypatch):
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_ENABLED", True)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_LOOKBACK_HOURS", 6)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_MAX_ARTICLES_PER_SOURCE", 30)

        now = datetime.now(timezone.utc)

        def _fake_parse(url):
            if "coindesk" in url:
                return _FakeParsed([_FakeEntry("Bitcoin surges", _struct_time(now))])
            if "cointelegraph" in url:
                return _FakeParsed([_FakeEntry("Market crash", _struct_time(now))])
            return _FakeParsed([])  # every other configured source: empty but ok

        monkeypatch.setattr("feedparser.parse", _fake_parse)
        monkeypatch.setattr(
            "vaderSentiment.vaderSentiment.SentimentIntensityAnalyzer", _FakeAnalyzer
        )

        result = refresh_news_sentiment()

        assert result["articles_scored"] == 2
        assert result["sources_ok"] == len(SOURCES)
        assert result["sources_failed"] == 0

        snap = get_news_sentiment_snapshot()
        assert snap.article_count == 2
        assert snap.score == pytest.approx(0.0)  # 0.8 + -0.8 averaged
        assert snap.as_of is not None

    def test_one_failing_source_does_not_block_others(self, monkeypatch):
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_ENABLED", True)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_LOOKBACK_HOURS", 6)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_MAX_ARTICLES_PER_SOURCE", 30)

        now = datetime.now(timezone.utc)

        def _fake_parse(url):
            if "coindesk" in url:
                raise RuntimeError("simulated network failure")
            return _FakeParsed([_FakeEntry("Bitcoin rally continues", _struct_time(now))])

        monkeypatch.setattr("feedparser.parse", _fake_parse)
        monkeypatch.setattr(
            "vaderSentiment.vaderSentiment.SentimentIntensityAnalyzer", _FakeAnalyzer
        )

        result = refresh_news_sentiment()

        assert result["sources_failed"] == 1
        assert result["sources_ok"] == len(SOURCES) - 1
        assert result["articles_scored"] == len(SOURCES) - 1  # one headline from every other source

    def test_all_sources_empty_produces_zero_score_zero_articles(self, monkeypatch):
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_ENABLED", True)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_LOOKBACK_HOURS", 6)
        monkeypatch.setattr("intelligence.news_sentiment_feed.settings.NEWS_SENTIMENT_MAX_ARTICLES_PER_SOURCE", 30)
        monkeypatch.setattr("feedparser.parse", lambda url: _FakeParsed([]))
        monkeypatch.setattr(
            "vaderSentiment.vaderSentiment.SentimentIntensityAnalyzer", _FakeAnalyzer
        )

        result = refresh_news_sentiment()
        assert result["articles_scored"] == 0
        snap = get_news_sentiment_snapshot()
        assert snap.score == 0.0
        assert snap.article_count == 0
        # as_of IS set (the job ran) even with zero articles — distinguishes
        # "ran, found nothing in-window" from "never ran" (as_of=None).
        assert snap.as_of is not None


class TestSources:

    def test_all_configured_sources_are_https(self):
        for name, url in SOURCES.items():
            assert url.startswith("https://"), f"{name} URL is not https"

    def test_source_count(self):
        assert len(SOURCES) == 8
