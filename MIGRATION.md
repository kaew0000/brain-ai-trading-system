# MIGRATION — News Sentiment: RSS Ingestion + VADER Scoring (V16 §69)

## Do you need to do anything?

**No, if `NEWS_SENTIMENT_ENABLED=false` (the default).** No background
job runs, no RSS feeds are fetched, and market_context's
`news_sentiment.article_count` stays `0` — byte-identical to before
this phase in every trading decision.

## If you want news sentiment ingested (dashboard/journal visibility only)

Set `NEWS_SENTIMENT_ENABLED=true` in your `.env`. On the configured
interval (`NEWS_SENTIMENT_INTERVAL_MINUTES`, default 15 minutes), a
background job will:

- Fetch all 8 configured RSS feeds (CoinDesk, Cointelegraph, Decrypt,
  The Block, CryptoSlate, The Defiant, NewsBTC, CryptoPotato).
- Score each headline published within `NEWS_SENTIMENT_LOOKBACK_HOURS`
  (default 6h) using VADER (offline, no API key needed).
- Cache the average score, visible in `market_context["news_
  sentiment"]` (surfaced via `/api/signals`'s `raw_features`, same as
  every other market_context field).

**This alone does not affect any trading decision** —
`ConfidenceEngine`'s `news_sentiment` weight stays `0.0` regardless.

## If you also want it to carry real decision weight

Additionally set `NEWS_SENTIMENT_LIVE_ENABLED=true`. The weight
applied is `NEWS_SENTIMENT_LIVE_WEIGHT` (default `5.0`, about 5% of
total confidence — deliberately small). No contradiction-penalty
mechanism exists for this category: an opposing sentiment reading can
never subtract confidence or block a trade, only fail to add to one.

**Recommended sequencing**: enable `NEWS_SENTIMENT_ENABLED` alone
first, observe the ingested sentiment in the dashboard/journal for a
while, and only enable `NEWS_SENTIMENT_LIVE_ENABLED` once you're
comfortable with what it's actually reporting for real market events.

No database migration — nothing new is written to the journal or any
persistent store by this phase; the sentiment cache is in-memory only
and rebuilds itself on the next scheduled run after any restart.

**Requires** outbound HTTPS access to the 8 configured feed domains
(no new inbound ports, no new credentials — RSS feeds are all public,
unauthenticated).

## Rollback

Set `NEWS_SENTIMENT_ENABLED=false` (and/or `NEWS_SENTIMENT_LIVE_
ENABLED=false`) and restart. No database migration either direction.
