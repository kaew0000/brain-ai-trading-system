"""tests/test_news_sentiment_live_enable_switch.py — V16 Phase 55.

Covers decision/confidence_engine.py::resolve_confidence_weights() and
settings.NEWS_SENTIMENT_LIVE_ENABLED — mirrors
tests/test_hft_flow_live_enable_switch.py's structure exactly, since
resolve_confidence_weights() now gates two independent slots
(hft_flow, news_sentiment) with the same shape. Also confirms enabling
news_sentiment's weight has zero effect on hft_flow's slot and vice
versa — the two opt-ins are fully independent.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_default_returns_default_weights_object(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", False)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", False)

    result = resolve_confidence_weights()

    assert result == DEFAULT_WEIGHTS
    assert result["news_sentiment"] == 0.0


def test_enabled_applies_live_weight(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", False)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 5.0)

    result = resolve_confidence_weights()

    assert result["news_sentiment"] == 5.0
    for key in ("smc", "volume", "oi", "funding", "regime", "hft_flow"):
        assert result[key] == DEFAULT_WEIGHTS[key]


def test_enabled_respects_custom_live_weight(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import resolve_confidence_weights
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 15.0)

    result = resolve_confidence_weights()

    assert result["news_sentiment"] == 15.0


def test_default_weights_never_mutated(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights

    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 999.0)
    resolve_confidence_weights()

    assert DEFAULT_WEIGHTS["news_sentiment"] == 0.0


def test_confidence_engine_construction_with_resolved_weights(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import ConfidenceEngine, resolve_confidence_weights

    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", False)
    engine_off = ConfidenceEngine(weights=resolve_confidence_weights())
    assert engine_off._weights["news_sentiment"] == 0.0

    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 5.0)
    engine_on = ConfidenceEngine(weights=resolve_confidence_weights())
    assert engine_on._weights["news_sentiment"] > 0.0


def test_news_sentiment_live_enabled_default_is_false():
    from config.settings import Settings
    s = Settings()
    assert s.NEWS_SENTIMENT_LIVE_ENABLED is False


def test_news_sentiment_live_weight_default_is_five():
    from config.settings import Settings
    s = Settings()
    assert s.NEWS_SENTIMENT_LIVE_WEIGHT == 5.0


# ── The two opt-ins (hft_flow / news_sentiment) are fully independent ──────

def test_enabling_news_sentiment_does_not_affect_hft_flow_slot(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import resolve_confidence_weights
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 5.0)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", False)

    result = resolve_confidence_weights()

    assert result["news_sentiment"] == 5.0
    assert result["hft_flow"] == 0.0


def test_enabling_hft_flow_does_not_affect_news_sentiment_slot(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 5.0)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", False)

    result = resolve_confidence_weights()

    assert result["hft_flow"] == 5.0
    assert result["news_sentiment"] == 0.0


def test_both_enabled_simultaneously(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 5.0)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "NEWS_SENTIMENT_LIVE_WEIGHT", 5.0)

    result = resolve_confidence_weights()

    assert result["hft_flow"] == 5.0
    assert result["news_sentiment"] == 5.0
