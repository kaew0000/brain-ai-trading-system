# PATCH NOTES — News Sentiment: RSS Ingestion + VADER Scoring (V16 §69)

Branch: `feat/news-sentiment-agent`
Base: `main` @ `544493b` (merge of PR #103, commission/fee backfill)

Closes the "News Sentiment Agent (Phase 55, observe-only, RSS feeds)"
item from the 2026-08-05 project tracker (flagged there as started
mid-session and never completed; a 2026-09-17 audit confirmed zero
trace of it anywhere in the repository).

## Section-numbering note

This branched from the same base (`544493b`) as the still-unmerged
`fix/test-housekeeping-batch` branch, whose own docs call itself
"§68". Both independently claim "the section after §67" — a real
collision. This phase is numbered §69, assuming
`fix/test-housekeeping-batch` merges first. **Merge that one before
this one** to avoid a header renumber; if merged in the other order,
swap one "§68"/"§69" header — no content changes needed either way.

## Design decisions (confirmed with the repo owner before implementation)

1. **Sentiment method: VADER** — lexicon-based, offline, no API key,
   deterministic, fully reproducible. Chosen over an LLM-based
   approach for lower cost/latency and easier validation against a
   real trading track record before trusting it with decision weight.
2. **8 RSS feeds**, all URL-verified against each publisher's own site
   / the FeedSpot RSS database before use — never guessed: CoinDesk,
   Cointelegraph, Decrypt, The Block (the tracker's original 4) +
   CryptoSlate, The Defiant, NewsBTC, CryptoPotato (added per "if it
   makes the system better, add it" — independent, reputable,
   market-news-focused outlets; NFT/podcast/VC-essay/exchange-
   marketing feeds deliberately excluded).
3. **Real decision weight, using the HFT Flow (§45) precedent exactly**
   — repo owner asked for weight "if it can't break trading, or
   recommend." Recommended and accepted: `DEFAULT_WEIGHTS["news_
   sentiment"] = 0.0` (present in the real formula, mathematically
   inert), with a separate `NEWS_SENTIMENT_LIVE_ENABLED`/`_WEIGHT`
   opt-in to raise it later — identical shape to `HFT_FLOW_LIVE_*`.

## A real architecture finding, surfaced rather than worked around

This codebase has two independent signal-fusion systems:
`ConfidenceEngine`'s category weights (where `hft_flow` lives, and
where `news_sentiment` was added) and `agents/ceo_agent.py`'s separate
"AI employee" weighted-vote system (its own `self.WEIGHTS`/
`_effective_weights()`, fully independent mechanism). `hft_flow` was
never registered as a CEO agent either. This phase follows that same
precedent — `news_sentiment` is wired **only** through
`ConfidenceEngine`, the mechanism already proven to have a hard,
mathematical "0.0 = provably inert" guarantee. Registering it as a CEO
agent too was considered and explicitly deferred: that system's own
cold-start/weighting behavior for a new, unvalidated voter has not
been audited, and mixing an unaudited path into a safety-motivated
rollout would defeat the purpose of the rollout.

## Implementation

- `intelligence/news_sentiment_feed.py` (new) — background-only, same
  shape as §67's `journal/fee_backfill.py`. `SOURCES` dict (8 URLs),
  `NewsSentimentSnapshot` dataclass, lock-protected singleton cache,
  `_fetch_one_source()` (one feed, one best-effort attempt, never
  raises, checks feedparser's `bozo` flag), `refresh_news_sentiment()`
  (the scheduled job's entry point — no-ops when disabled).
- `intelligence/market_context_builder.py` — reused the existing,
  previously-always-`None` `"news_sentiment"` key (`intelligence`
  Layer-2 placeholder every caller has always passed `None` for)
  rather than adding a new one.
- `decision/confidence_engine.py` — `DEFAULT_WEIGHTS["news_
  sentiment"] = 0.0`; `resolve_confidence_weights()` extended with an
  independent `NEWS_SENTIMENT_LIVE_ENABLED`/`_WEIGHT` pair;
  `_score_news_sentiment()` (0.0-1.0, VADER's compound maps directly
  since it's already -1..+1 with true 0 as neutral); additive term
  gated on `article_count > 0`. No contradiction-penalty mechanism —
  unlike `hft_flow`, opposing sentiment floors at 0, never subtracts
  or blocks (headline sentiment is a noisier, lower-conviction signal
  than order-flow microstructure).
- `main.py::run_news_sentiment_job(sys)` — mirrors
  `run_fee_backfill_job()`'s guarded shape exactly.
- `config/settings.py` — 6 new settings (`NEWS_SENTIMENT_ENABLED`,
  `_INTERVAL_MINUTES`, `_LOOKBACK_HOURS`,
  `_MAX_ARTICLES_PER_SOURCE`, `_LIVE_ENABLED`, `_LIVE_WEIGHT`), all
  off/inert by default.
- `.env.example` — documents all 6 new settings; also retroactively
  adds §67's `FEE_BACKFILL_*` block (an oversight from that phase,
  fixed here).
- `requirements.txt` — `feedparser>=6.0.10`, `vaderSentiment>=3.3.2`
  (both pure-Python, no native build step).

## Tests

47 new tests across 4 files — see `docs/architecture.md` §69's Testing
section for the full breakdown. All 3141 pre-existing tests pass
unchanged, including the full existing `hft_flow` suite (38 tests,
zero regressions — confirms the two opt-in mechanisms really are
independent).

Full suite: `pytest` → **3188 passed** (up from 3141), 4 skipped, 45
deselected, **0 failures**.

`ruff check . --exclude dashboard_src --exclude dashboard` → all
checks passed. `vulture . --exclude dashboard_src,dashboard,tests
--min-confidence 80` → clean on every changed/new source file.
`python -c "import main"` → succeeds.

## With this, the 2026-08-05 project tracker's entire backlog is closed

Fee capture (§67, merged), test/tooling housekeeping (§68, delivered,
awaiting merge), and now News Sentiment (§69) — the last item that
required actual implementation work. Remaining out-of-scope items
(Binance API 401/IP whitelist — external account config;
`fix/office-scene-real-assets` — paused World work) stay as they were.

## Files changed

`.env.example`, `config/settings.py`, `decision/confidence_engine.py`,
`intelligence/market_context_builder.py`,
`intelligence/news_sentiment_feed.py` (new), `main.py`,
`requirements.txt`, `tests/test_market_context_news_sentiment.py`
(new), `tests/test_news_sentiment_confidence_integration.py` (new),
`tests/test_news_sentiment_feed.py` (new),
`tests/test_news_sentiment_live_enable_switch.py` (new),
`PATCH_NOTES.md`, `MIGRATION.md`, `CHANGELOG.md`,
`docs/architecture.md` (§69).
