"""
tests/test_recommendation_context.py — V16 Phase 4C Step 3
(learning/application/recommendation_context.py)

Covers Part I's "loading, filtering, expiry, contradiction" requirements.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from learning.application.recommendation_context import (
    RecommendationSet,
    build_recommendation_set,
)
from learning.pattern_miner import Pattern
from learning.recommendation_engine import RecommendationEngine

pytestmark = pytest.mark.unit


def _pattern(kind, subject, metric=None, severity="negative"):
    return Pattern(kind=kind, subject=subject, metric=metric or {"win_rate": 0.3, "sample_size": 40},
                   description="d", severity=severity)


class TestLoadingAndBasicFiltering:

    def test_empty_input_gives_empty_set(self):
        rset = build_recommendation_set([])
        assert rset.applied == [] and rset.skipped == []

    def test_no_filters_applies_every_valid_recommendation(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT"), _pattern("worst_symbol", "ETHUSDT")], now=now,
        )
        rset = build_recommendation_set(recs, now=now)
        assert len(rset.applied) == 2
        assert rset.skipped == []

    def test_symbol_filter_excludes_other_symbols(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT"), _pattern("worst_symbol", "ETHUSDT")], now=now,
        )
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        assert [r.symbol for r in rset.applied] == ["BTCUSDT"]
        assert rset.skipped[0].reason == "symbol_mismatch"

    def test_symbol_agnostic_recommendation_survives_symbol_filter(self):
        """A worst_regime recommendation has no .symbol — must not be
        excluded just because the caller asked for one symbol."""
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_regime", "HIGH_VOL")], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        assert len(rset.applied) == 1
        assert rset.applied[0].regime == "HIGH_VOL"

    def test_regime_filter_excludes_other_regimes(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol_regime_combo", "BTCUSDT/HIGH_VOL"),
             _pattern("worst_symbol_regime_combo", "BTCUSDT/TREND_UP")], now=now,
        )
        rset = build_recommendation_set(recs, regime="HIGH_VOL", now=now)
        assert len(rset.applied) == 1
        assert rset.applied[0].regime == "HIGH_VOL"

    def test_min_confidence_filter(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT", metric={"win_rate": 0.3, "sample_size": 60}),   # high
             _pattern("worst_symbol", "ETHUSDT", metric={"win_rate": 0.3, "sample_size": 15})],   # medium
            now=now,
        )
        rset = build_recommendation_set(recs, min_confidence="high", now=now)
        assert len(rset.applied) == 1
        assert rset.applied[0].confidence == "high"
        assert rset.skipped[0].reason == "below_min_confidence"

    def test_direction_filter_is_noop_today_since_direction_is_always_none(self):
        """Documents the honest current behavior: no pattern kind this
        engine produces has a non-None .direction, so filtering by
        direction never excludes anything today."""
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        rset = build_recommendation_set(recs, direction="LONG", now=now)
        assert len(rset.applied) == 1


class TestExpiry:

    def test_expired_recommendation_is_skipped(self):
        now = datetime.now(timezone.utc)
        old = now - timedelta(hours=48)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=old)
        rset = build_recommendation_set(recs, now=now)
        assert rset.applied == []
        assert rset.skipped[0].reason == "validator_status=expired"

    def test_fresh_recommendation_is_not_expired(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        rset = build_recommendation_set(recs, now=now)
        assert len(rset.applied) == 1


class TestContradiction:

    def test_best_and_worst_confidence_range_contradict(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_confidence_range", "60-80", metric={"win_rate": 0.3, "sample_size": 40}, severity="negative"),
             _pattern("best_confidence_range", "40-60", metric={"win_rate": 0.7, "sample_size": 40}, severity="positive")],
            now=now,
        )
        rset = build_recommendation_set(recs, now=now)
        assert rset.applied == []
        reasons = {s.reason for s in rset.skipped}
        assert all(r.startswith("contradicted_by=") for r in reasons)

    def test_different_symbols_do_not_contradict(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol_regime_combo", "BTCUSDT/HIGH_VOL"),
             _pattern("best_symbol_regime_combo", "ETHUSDT/TREND_UP", severity="positive",
                      metric={"win_rate": 0.8, "sample_size": 40})],
            now=now,
        )
        rset = build_recommendation_set(recs, now=now)
        assert len(rset.applied) == 2

    def test_different_categories_do_not_contradict(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate(
            [_pattern("worst_symbol", "BTCUSDT"),
             _pattern("best_confidence_range", "40-60", severity="positive",
                      metric={"win_rate": 0.7, "sample_size": 40})],
            now=now,
        )
        rset = build_recommendation_set(recs, now=now)
        assert len(rset.applied) == 2


class TestAlreadyValidated:

    def test_skips_revalidation_when_already_validated_true(self):
        """A recommendation manually marked 'expired' should be trusted
        as-is when already_validated=True, even though re-validating it
        from scratch would say 'valid'."""
        from dataclasses import replace
        now = datetime.now(timezone.utc)
        rec = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)[0]
        forced = replace(rec, validator_status="expired")
        rset = build_recommendation_set([forced], now=now, already_validated=True)
        assert rset.applied == []
        assert rset.skipped[0].reason == "validator_status=expired"


class TestRecommendationSetToDict:

    def test_to_dict_is_json_shaped(self):
        now = datetime.now(timezone.utc)
        recs = RecommendationEngine().generate([_pattern("worst_symbol", "BTCUSDT")], now=now)
        rset = build_recommendation_set(recs, symbol="BTCUSDT", now=now)
        d = rset.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert isinstance(d["applied"], list) and isinstance(d["skipped"], list)
        assert d["applied"][0]["symbol"] == "BTCUSDT"

    def test_empty_set_shape(self):
        rset = RecommendationSet(symbol=None, regime=None, direction=None, generated_at="x")
        assert rset.to_dict()["applied"] == []
        assert rset.to_dict()["skipped"] == []
