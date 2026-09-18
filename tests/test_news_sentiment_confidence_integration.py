"""tests/test_news_sentiment_confidence_integration.py — V16 Phase 55.

Covers decision/confidence_engine.py's News Sentiment integration:
- The additive news_sentiment category (weight 0.0 by default — inert,
  but functional when explicitly raised).
- No contradiction-penalty mechanism exists for this category (unlike
  hft_flow) — opposing sentiment floors at 0, never blocks or penalizes.
- Backward-compat: with everything at its shipped default, byte-
  identical to before this phase (mirrors
  tests/test_hft_flow_confidence_integration.py's own structure and
  reasoning).
"""
import pytest

from decision.confidence_engine import ConfidenceEngine, DEFAULT_WEIGHTS

pytestmark = pytest.mark.unit


def _news_sentiment(score=0.0, article_count=1, as_of="2026-09-17T00:00:00+00:00"):
    return {
        "score": score, "article_count": article_count, "as_of": as_of,
        "sources_ok": 8, "sources_failed": 0,
    }


def _ctx(news_sentiment=None, blocks_long=False, blocks_short=False):
    ctx = {
        "regime": "TREND", "trend_bias": "LONG_BIAS", "trend_strength": "STRONG",
        "smc_m15": {}, "volume": {},
        "futures": {"funding": {}, "open_interest": {}},
        "oi_delta": 0.0, "funding_rate": 0.0001,
        "blocks_long": blocks_long, "blocks_short": blocks_short,
        "mtf_aligned": True,
    }
    if news_sentiment is not None:
        ctx["news_sentiment"] = news_sentiment
    return ctx


def _engine(weights=None):
    return ConfidenceEngine(weights=weights)


# ── Default weight (0.0) — inert, but breakdown key visible when data active ─

def test_default_weight_is_zero():
    assert DEFAULT_WEIGHTS["news_sentiment"] == 0.0


def test_breakdown_gains_news_sentiment_key_only_when_article_count_positive():
    engine = _engine()
    ctx_inactive = _ctx(news_sentiment=_news_sentiment(score=0.8, article_count=0))
    ctx_active = _ctx(news_sentiment=_news_sentiment(score=0.8, article_count=1))
    result_inactive = engine.score(ctx_inactive, "LONG")
    result_active = engine.score(ctx_active, "LONG")
    assert "news_sentiment" not in result_inactive.breakdown
    assert result_active.breakdown["news_sentiment"] == 0  # weight still 0.0 by default


def test_no_news_sentiment_key_at_all_leaves_breakdown_unchanged():
    engine = _engine()
    ctx = _ctx(news_sentiment=None)  # context has no "news_sentiment" key at all
    result = engine.score(ctx, "LONG")
    assert "news_sentiment" not in result.breakdown
    assert set(result.breakdown.keys()) == {"smc", "volume", "oi", "funding", "regime"}


def test_empty_news_sentiment_dict_leaves_breakdown_unchanged():
    """The real shape market_context_builder.py always supplies — an
    all-default dict (article_count=0) before the background job has
    ever run, not a missing key."""
    engine = _engine()
    ctx = _ctx(news_sentiment={"score": 0.0, "article_count": 0, "as_of": None,
                                "sources_ok": 0, "sources_failed": 0})
    result = engine.score(ctx, "LONG")
    assert "news_sentiment" not in result.breakdown


# ── Additive term actually working when weight is explicitly raised ─────────

def test_positive_weight_and_aligned_sentiment_increases_confidence():
    baseline_weights = dict(DEFAULT_WEIGHTS)
    news_weights = dict(DEFAULT_WEIGHTS)
    news_weights["news_sentiment"] = 5.0
    baseline_engine = _engine(weights=baseline_weights)
    news_engine = _engine(weights=news_weights)

    ctx = _ctx(news_sentiment=_news_sentiment(score=0.8, article_count=12))
    baseline_result = baseline_engine.score(ctx, "LONG")
    news_result = news_engine.score(ctx, "LONG")

    assert news_result.breakdown["news_sentiment"] > 0
    assert news_result.confidence >= baseline_result.confidence


def test_opposing_sentiment_contributes_zero_not_negative():
    news_weights = dict(DEFAULT_WEIGHTS)
    news_weights["news_sentiment"] = 5.0
    engine = _engine(weights=news_weights)
    ctx = _ctx(news_sentiment=_news_sentiment(score=-0.8, article_count=12))
    result = engine.score(ctx, "LONG")
    assert result.breakdown["news_sentiment"] == 0  # not negative — floors at 0


def test_neutral_sentiment_contributes_zero():
    news_weights = dict(DEFAULT_WEIGHTS)
    news_weights["news_sentiment"] = 5.0
    engine = _engine(weights=news_weights)
    ctx = _ctx(news_sentiment=_news_sentiment(score=0.0, article_count=12))
    result = engine.score(ctx, "LONG")
    assert result.breakdown["news_sentiment"] == 0


def test_short_direction_uses_opposite_sign_convention():
    news_weights = dict(DEFAULT_WEIGHTS)
    news_weights["news_sentiment"] = 5.0
    engine = _engine(weights=news_weights)
    ctx = _ctx(news_sentiment=_news_sentiment(score=-0.8, article_count=12))
    result = engine.score(ctx, "SHORT")
    assert result.breakdown["news_sentiment"] > 0  # negative headlines favor a SHORT


# ── _score_news_sentiment direct unit tests ──────────────────────────────

def test_score_news_sentiment_zero_articles_returns_zero():
    ctx = _ctx(news_sentiment=_news_sentiment(score=0.9, article_count=0))
    assert ConfidenceEngine._score_news_sentiment(ctx, "LONG") == 0.0


def test_score_news_sentiment_scales_with_vader_compound():
    ctx = _ctx(news_sentiment=_news_sentiment(score=0.5, article_count=5))
    assert ConfidenceEngine._score_news_sentiment(ctx, "LONG") == pytest.approx(0.5)


def test_score_news_sentiment_clamped_at_one():
    # VADER's compound is already bounded to [-1, 1], but the scorer
    # clamps defensively anyway — same convention as _score_hft_flow.
    ctx = _ctx(news_sentiment=_news_sentiment(score=1.0, article_count=5))
    assert ConfidenceEngine._score_news_sentiment(ctx, "LONG") == pytest.approx(1.0)


def test_score_news_sentiment_empty_direction_returns_zero():
    ctx = _ctx(news_sentiment=_news_sentiment(score=0.9, article_count=5))
    assert ConfidenceEngine._score_news_sentiment(ctx, "") == 0.0


def test_score_news_sentiment_missing_key_returns_zero():
    ctx = _ctx(news_sentiment=None)
    assert ConfidenceEngine._score_news_sentiment(ctx, "LONG") == 0.0
