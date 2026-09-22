# MIGRATION — News Sentiment Feed Hardening (V16 §71)

## Do you need to do anything?

**No.** Both fixes are drop-in and backward compatible.

- The new `NEWS_SENTIMENT_FETCH_TIMEOUT_SECONDS` setting defaults to
  `10` seconds. No `.env` change is required — this is only worth
  tuning if a specific configured RSS source is known to be slow but
  reliable (e.g. behind a proxy) and worth waiting longer for. It has
  been added to `.env.example` for discoverability, matching every
  other `NEWS_SENTIMENT_*` setting already documented there.
- The `ml/extensions/` timestamp fields (`last_drift_time`, trial/
  bundle `timestamp`, `completed_at`) change from naive to
  timezone-aware `datetime.now(timezone.utc)`. The only externally
  visible effect is that their `.isoformat()` string representation
  gains a `+00:00` suffix (e.g. `2026-09-22T10:15:00` →
  `2026-09-22T10:15:00+00:00`). Nothing in the repo currently parses
  these specific fields back into a `datetime` for comparison, so
  there is nothing to update. If any external tooling outside this
  repo parses these fields with a strict format string that doesn't
  expect a UTC offset, it would need updating — none is known to
  exist.

No database migration, no API contract change, no rollback
considerations beyond a normal `git revert` if ever needed.
