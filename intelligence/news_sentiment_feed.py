"""
News Sentiment — background RSS ingestion + VADER scoring (V16 Phase 55).

Root cause this closes: the 2026-08-05 project tracker listed a "News
Sentiment Agent (Phase 55, observe-only, RSS feeds)" as partially
started mid-session and never completed — no trace of it existed
anywhere in the repository as of the 2026-09-17 audit.

Design (mirrors journal/fee_backfill.py's shape exactly, for the same
reasons): background-only, never called from the live trading cycle.
A scheduled job (main.py's run_news_sentiment_job()) calls
refresh_news_sentiment() on an interval; market_context_builder.py
reads the cached result via get_news_sentiment_snapshot() when
assembling each cycle's market_context. The fetch and the read are
fully decoupled — a slow or failing RSS fetch can never block or delay
a trading decision, only leave the cache stale (which is itself
visible via the snapshot's `as_of`/`stale` fields).

Sentiment method: VADER (Valence Aware Dictionary and sEntiment
Reasoner) — a lexicon-based, offline sentiment analyzer. No API key,
no network call beyond the RSS fetch itself, deterministic, sub-
millisecond per headline. Chosen over an LLM-based approach for this
first iteration: lower cost, lower latency, no additional external
dependency in the fetch path, and — per this module's own design goal
of eventually earning real decision weight (see decision/
confidence_engine.py's news_sentiment slot) — a simpler, fully
inspectable scoring method is easier to validate against a real
trading track record than an LLM call whose reasoning isn't
reproducible run to run.

Scored on headlines (entry.title) only, not full article bodies —
feedparser doesn't reliably expose full body text across all these
feeds' RSS formats, and headlines are what VADER-style lexicon
scoring was validated against in the literature it comes from
(social-media-length text), not long-form prose.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from config.settings import settings
from utils.logger import get_logger

logger = get_logger(__name__)

# Verified live RSS feed URLs (confirmed against each publisher's own
# site / the FeedSpot RSS database, 2026-09-17) — not guessed. If one
# goes offline or changes its URL, refresh_news_sentiment() just logs a
# skip for that source and keeps going (see its docstring); update the
# URL here to fix it, or remove the entry to drop that source.
SOURCES: dict[str, str] = {
    "coindesk":       "https://www.coindesk.com/arc/outboundfeeds/rss",
    "cointelegraph":  "https://cointelegraph.com/rss",
    "decrypt":        "https://decrypt.co/feed",
    "theblock":       "https://www.theblock.co/rss.xml",
    "cryptoslate":    "https://cryptoslate.com/feed/",
    "thedefiant":     "https://thedefiant.io/api/feed",
    "newsbtc":        "https://www.newsbtc.com/feed/",
    "cryptopotato":   "https://cryptopotato.com/feed/",
}


@dataclass
class NewsSentimentSnapshot:
    """What market_context_builder.py reads. `score` is VADER's compound
    score averaged across all in-window headlines, range -1.0 (most
    negative) to +1.0 (most positive); 0.0 with article_count == 0 means
    "no data" (either the job hasn't run yet, or nothing published in
    the lookback window), never "neutral sentiment" fabricated from
    nothing — decision/confidence_engine.py's news_sentiment_active gate
    reads article_count, not score, to tell the two apart."""
    score:          float = 0.0
    article_count:  int   = 0
    as_of:          str | None = None   # ISO 8601 UTC; None until the first run
    sources_ok:     int   = 0
    sources_failed: int   = 0

    def is_stale(self, max_age_minutes: float) -> bool:
        if self.as_of is None:
            return True
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(self.as_of)
        except ValueError:
            return True
        return age > timedelta(minutes=max_age_minutes)


class _NewsSentimentCache:
    """Module-level singleton, same "background job writes, request path
    reads" shape as telemetry/account_state.py. A plain lock is enough —
    this is written once per NEWS_SENTIMENT_INTERVAL_MINUTES by the
    scheduler thread and read every trading cycle; no meaningful
    contention."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot = NewsSentimentSnapshot()

    def get(self) -> NewsSentimentSnapshot:
        with self._lock:
            return self._snapshot

    def set(self, snapshot: NewsSentimentSnapshot) -> None:
        with self._lock:
            self._snapshot = snapshot


_cache = _NewsSentimentCache()


def get_news_sentiment_snapshot() -> NewsSentimentSnapshot:
    """market_context_builder.py's read side. Always returns a
    NewsSentimentSnapshot — an all-default one (article_count=0,
    as_of=None) before the first successful run, or if
    NEWS_SENTIMENT_ENABLED is False, matching hft_flow's
    all-default-until-opted-in convention."""
    return _cache.get()


def _fetch_one_source(name: str, url: str, analyzer, cutoff: datetime, max_articles: int) -> tuple[list[float], bool]:
    """One feed, one best-effort fetch — never raises. Returns
    (list of VADER compound scores for in-window headlines, ok).
    `ok` is False on a fetch/parse failure (feedparser's own `bozo`
    flag, or any exception) — that source is simply skipped for this
    run, same as every RSS-consuming reference implementation checked
    while designing this module."""
    import feedparser

    try:
        parsed = feedparser.parse(url)
    except Exception as exc:
        logger.warning(f"news_sentiment: fetch failed for {name}: {exc}")
        return [], False

    if getattr(parsed, "bozo", False):
        logger.warning(
            f"news_sentiment: malformed/unreachable feed for {name}: "
            f"{getattr(parsed, 'bozo_exception', 'unknown error')}"
        )
        return [], False

    scores: list[float] = []
    for entry in (parsed.entries or [])[:max_articles]:
        title = getattr(entry, "title", None)
        if not title:
            continue
        published = getattr(entry, "published_parsed", None)
        if published is not None:
            try:
                pub_dt = datetime(*published[:6], tzinfo=timezone.utc)
                if pub_dt < cutoff:
                    continue
            except (TypeError, ValueError):
                pass  # unparseable date — score it anyway rather than drop it
        scores.append(analyzer.polarity_scores(title)["compound"])

    return scores, True


def refresh_news_sentiment() -> dict:
    """Entry point for the scheduled job (main.py's
    run_news_sentiment_job()). Returns a summary dict for logging —
    never raises. No-ops when settings.NEWS_SENTIMENT_ENABLED is False.
    """
    summary = {"sources_ok": 0, "sources_failed": 0, "articles_scored": 0}
    if not settings.NEWS_SENTIMENT_ENABLED:
        return summary

    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

    analyzer = SentimentIntensityAnalyzer()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.NEWS_SENTIMENT_LOOKBACK_HOURS)

    all_scores: list[float] = []
    for name, url in SOURCES.items():
        scores, ok = _fetch_one_source(
            name, url, analyzer, cutoff, settings.NEWS_SENTIMENT_MAX_ARTICLES_PER_SOURCE
        )
        if ok:
            summary["sources_ok"] += 1
        else:
            summary["sources_failed"] += 1
        all_scores.extend(scores)

    summary["articles_scored"] = len(all_scores)

    avg_score = sum(all_scores) / len(all_scores) if all_scores else 0.0
    _cache.set(NewsSentimentSnapshot(
        score=round(avg_score, 4),
        article_count=len(all_scores),
        as_of=datetime.now(timezone.utc).isoformat(),
        sources_ok=summary["sources_ok"],
        sources_failed=summary["sources_failed"],
    ))
    return summary
