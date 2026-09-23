# PATCH NOTES — News Sentiment Feed Hardening (V16 §71)

Branch: `fix/news-sentiment-timeout-and-tz-hardening`
Base: `main` @ `7d3dca6` (merge of PR #105, test/tooling housekeeping
batch, §70)

Closes two review-discovered latent bugs found in a code-level review
pass over the work delivered in §69 (News Sentiment) and the wider
`ml/extensions/` package — not new features, hardening of existing
code. Grouped into one phase per this repo's own "housekeeping batch"
precedent (§70): both are review-found, both are small, neither
touches the other's files. Full root-cause detail in
`docs/architecture.md` §71; this file summarizes.

## Item 1: `intelligence/news_sentiment_feed.py` — unbounded fetch hang

### Root cause

`_fetch_one_source()` called `feedparser.parse(url)` directly.
`feedparser.parse()` has no timeout of its own when given a URL — a
known limitation of the library (see feedparser#76) — so an
unresponsive RSS server would hang the call indefinitely. This job
runs on main.py's single shared `schedule.run_pending()` loop, the
same loop that runs `run_trading_cycle` — an unbounded hang here would
have delayed live trading itself, not just left the sentiment cache
stale as the module's own docstring implied.

The project's own convention for this exact situation already existed
and was missed: `intelligence/market_intelligence_service.py`'s
`FearGreedProvider.fetch()` — the only other synchronous external-feed
fetch in the codebase — already uses `requests.get(url, timeout=5)`.

### Fix

`_fetch_one_source()` now does:

```python
response = requests.get(url, timeout=settings.NEWS_SENTIMENT_FETCH_TIMEOUT_SECONDS)
response.raise_for_status()
parsed = feedparser.parse(response.content)
```

instead of `feedparser.parse(url)`. Both calls stay inside the
existing single try/except, so the function's "never raises" contract
is unchanged — a connection failure, an HTTP error status, and a
feedparser parse failure all land in the same `sources_failed` path
as before. New setting `NEWS_SENTIMENT_FETCH_TIMEOUT_SECONDS` (default
`10`) added to `config/settings.py` and `.env.example`, same
`_TIMEOUT_SECONDS` naming convention as the existing
`BUNDLE_GIT_TIMEOUT_SECONDS`. Module docstring corrected: the
fetch/read decoupling claim now correctly states it depends on the
fetch being time-bounded, rather than implying it was unconditionally
safe regardless of fetch duration.

## Item 2: naive `datetime.now()` in four `ml/extensions/` files

### Root cause

`ml/extensions/online/learner.py`, `ml/extensions/hpo/manager.py`,
`ml/extensions/orchestrator.py`, and `ml/extensions/rl/adapter.py`
all used naive `datetime.now()` for timestamp fields (`last_drift_time`,
trial/bundle `timestamp`, `completed_at`). A repo-wide grep confirmed
these 4 files are the only non-test code using naive `datetime.now()`
— every other timestamp-producing module (journal, telemetry,
fee_backfill, and news_sentiment above) already uses
`datetime.now(timezone.utc)`. Latent rather than active today — these
values currently only reach `.isoformat()` for logging/storage, never
compared against another datetime. Forward risk: any future code that
compares one of these fields against an aware timestamp (the shape
`NewsSentimentSnapshot.is_stale()` above already uses) would raise
`TypeError: can't subtract offset-naive and offset-aware datetimes`;
on a host not running in UTC, the value would also be silently wrong.

### Fix

All four files: `from datetime import datetime` →
`from datetime import datetime, timezone`; every `datetime.now()` →
`datetime.now(timezone.utc)`. No field names, formats, or call
signatures changed — `.isoformat()` output only gains a `+00:00`
offset suffix. No existing test asserted on the naive form.

## Testing

`tests/test_news_sentiment_feed.py`: 21 existing tests migrated to
mock `requests.get` (returning a fake response whose `.content` is the
requested URL, re-decoded inside the `feedparser.parse` mock, so every
existing per-source differentiation test needed no logic changes)
instead of mocking `feedparser.parse(url)` directly. 2 new tests:
`test_fetch_uses_configured_timeout` (regression test proving
`requests.get` is actually called with
`NEWS_SENTIMENT_FETCH_TIMEOUT_SECONDS` — the root-cause assertion) and
`test_http_error_status_returns_not_ok` (new `raise_for_status()`
path). **23/23 passed.**

Full suite (against this branch, base `main` @ `7d3dca6`): **3189
passed, 45 deselected, 0 failed** attributable to this change. 7
pre-existing failures reproduced identically on unmodified `main`
before this diff was applied (confirmed by stash/verify, not assumed):
3 in `tests/test_dashboard_serving.py` (documented since §67 —
requires `npm run build` in `dashboard_src/`, absent from this
sandbox) and 4 in `tests/test_ml_extensions_integration.py`
(`stable_baselines3` not installed in this sandbox — an optional,
gracefully-degrading dependency of the ML Extensions layer; the
suite's usual "4 skipped" elsewhere for `gymnasium`-gated tests
confirms this sandbox matches the project's own reference test
environment, which also lacks this optional stack).

`ruff check .`: **clean, repo-wide.**
`vulture . --min-confidence 80`: **clean on every changed file**
(whole-repo run surfaces only pre-existing, unrelated warnings in
untouched test files).
`python -c "import main"`: **succeeds.**
