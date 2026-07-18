"""
tests/test_opportunity_ranker.py — V16 Phase 2 Part 2: Opportunity Ranking
Engine test suite.

Every input is a hand-built SymbolSnapshot or MagicMock scanner — no
network calls, no real MarketScanner instance running. Persistence tests
use the same `:memory:` DATABASE_PATH pattern as tests/test_market_scanner.py.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from scanner.market_scanner import SymbolSnapshot
from ranking.ranking_models import FactorScore, ScoreBreakdown, ScoreStatus, RankedOpportunity
from ranking import score_breakdown as sb
from ranking.confidence_fusion import fuse
from ranking.opportunity_ranker import OpportunityRanker
from ranking import ranking_history

pytestmark = pytest.mark.unit


def _snap(symbol="BTCUSDT", price=65000.0, chg=2.5, vol=5e8, funding=0.0001,
          spread=0.0002, oi=1.2e9, atr=0.018, scanned_at=None, detail_at=None):
    now = scanned_at if scanned_at is not None else time.time()
    return SymbolSnapshot(
        symbol=symbol, price=price, price_change_pct_24h=chg,
        quote_volume_24h=vol, funding_rate=funding, spread_pct=spread,
        open_interest=oi, atr_pct=atr, scanned_at=now,
        detail_at=(detail_at if detail_at is not None else now),
    )


# ── score_breakdown.py: individual factors ──────────────────────────────────

class TestFactorScoring:

    def test_trend_scores_magnitude_not_direction(self):
        up   = sb.score_trend(_snap(chg=5.0))
        down = sb.score_trend(_snap(chg=-5.0))
        assert up.score == pytest.approx(down.score)
        assert up.status == ScoreStatus.COMPUTED

    def test_trend_flat_scores_low(self):
        flat = sb.score_trend(_snap(chg=0.05))
        strong = sb.score_trend(_snap(chg=9.0))
        assert flat.score < strong.score

    def test_momentum_rewards_funding_agreement(self):
        agrees    = sb.score_momentum(_snap(chg=5.0, funding=0.0005))
        disagrees = sb.score_momentum(_snap(chg=5.0, funding=-0.0005))
        assert agrees.score > disagrees.score

    def test_volume_percentile_is_relative_to_universe(self):
        stats = sb.compute_universe_stats([_snap(vol=1e6), _snap(vol=5e8), _snap(vol=1e9)])
        low  = sb.score_volume(_snap(vol=1e6), stats)
        high = sb.score_volume(_snap(vol=1e9), stats)
        assert high.score > low.score

    def test_funding_near_zero_scores_high(self):
        neutral = sb.score_funding(_snap(funding=0.00001))
        extreme = sb.score_funding(_snap(funding=0.002))
        assert neutral.score > extreme.score

    def test_open_interest_unavailable_when_none(self):
        f = sb.score_open_interest(_snap(oi=None), sb.compute_universe_stats([_snap(oi=None)]))
        assert f.status == ScoreStatus.UNAVAILABLE
        assert f.score == 50.0

    def test_open_interest_computed_when_present(self):
        stats = sb.compute_universe_stats([_snap(oi=1e6), _snap(oi=1e9)])
        f = sb.score_open_interest(_snap(oi=1e9), stats)
        assert f.status == ScoreStatus.COMPUTED
        assert f.score > 50.0

    def test_liquidity_blends_volume_and_spread(self):
        stats = sb.compute_universe_stats([_snap(vol=1e6, spread=0.002), _snap(vol=1e9, spread=0.0001)])
        good = sb.score_liquidity(_snap(vol=1e9, spread=0.0001), stats)
        bad  = sb.score_liquidity(_snap(vol=1e6, spread=0.002), stats)
        assert good.score > bad.score

    def test_spread_tighter_scores_higher(self):
        tight = sb.score_spread(_snap(spread=0.0001))
        wide  = sb.score_spread(_snap(spread=0.002))
        assert tight.score > wide.score

    def test_risk_unavailable_when_atr_none(self):
        f = sb.score_risk(_snap(atr=None))
        assert f.status == ScoreStatus.UNAVAILABLE

    def test_risk_lower_volatility_scores_higher(self):
        calm    = sb.score_risk(_snap(atr=0.005))
        violent = sb.score_risk(_snap(atr=0.05))
        assert calm.score > violent.score

    def test_market_structure_always_unavailable(self):
        assert sb.score_market_structure(_snap()).status == ScoreStatus.UNAVAILABLE

    def test_ai_confidence_always_unavailable(self):
        assert sb.score_ai_confidence(_snap()).status == ScoreStatus.UNAVAILABLE

    def test_historical_performance_always_unavailable(self):
        assert sb.score_historical_performance(_snap()).status == ScoreStatus.UNAVAILABLE

    def test_all_scores_bounded_0_100(self):
        stats = sb.compute_universe_stats([_snap()])
        breakdown = sb.score_symbol(_snap(chg=50.0, funding=0.5, spread=0.5, atr=5.0), stats)
        for f in breakdown.factors.values():
            assert 0.0 <= f.score <= 100.0

    def test_score_symbol_returns_exactly_eleven_factors(self):
        stats = sb.compute_universe_stats([_snap()])
        breakdown = sb.score_symbol(_snap(), stats)
        assert len(breakdown.factors) == 11
        assert set(breakdown.factors) == set(sb._ALL_FACTORS)


class TestUniverseStats:

    def test_empty_snapshots_percentile_defaults_to_50(self):
        stats = sb.compute_universe_stats([])
        assert stats.volume_percentile(1e9) == 50.0

    def test_single_snapshot_percentile_defaults_to_50(self):
        stats = sb.compute_universe_stats([_snap(vol=1e9)])
        assert stats.volume_percentile(1e9) == 50.0

    def test_oi_coverage_counts_only_symbols_with_oi(self):
        stats = sb.compute_universe_stats([_snap(oi=1e6), _snap(oi=None), _snap(oi=2e6)])
        assert stats.oi_coverage == 2


# ── confidence_fusion.py ─────────────────────────────────────────────────────

class TestConfidenceFusion:

    def test_full_coverage_when_all_computed(self):
        breakdown = ScoreBreakdown(symbol="X", factors={
            "a": FactorScore("a", 80, ScoreStatus.COMPUTED, "x"),
            "b": FactorScore("b", 60, ScoreStatus.COMPUTED, "x"),
        })
        composite, coverage, _ = fuse(breakdown, weights={"a": 50, "b": 50})
        assert composite == pytest.approx(70.0)
        assert coverage == pytest.approx(1.0)

    def test_unavailable_factors_excluded_and_coverage_reflects_it(self):
        breakdown = ScoreBreakdown(symbol="X", factors={
            "a": FactorScore("a", 90, ScoreStatus.COMPUTED, "x"),
            "b": FactorScore("b", 50, ScoreStatus.UNAVAILABLE, "x"),
        })
        composite, coverage, _ = fuse(breakdown, weights={"a": 50, "b": 50})
        assert composite == pytest.approx(90.0)  # not diluted by b's placeholder
        assert coverage == pytest.approx(0.5)

    def test_all_unavailable_falls_back_to_neutral(self):
        breakdown = ScoreBreakdown(symbol="X", factors={
            "a": FactorScore("a", 50, ScoreStatus.UNAVAILABLE, "x"),
        })
        composite, coverage, _ = fuse(breakdown, weights={"a": 100})
        assert composite == 50.0
        assert coverage == 0.0

    def test_explanation_lists_unavailable_factors_by_name(self):
        breakdown = ScoreBreakdown(symbol="BTCUSDT", factors={
            "a": FactorScore("a", 80, ScoreStatus.COMPUTED, "x"),
            "market_structure": FactorScore("market_structure", 50, ScoreStatus.UNAVAILABLE, "x"),
        })
        _, _, explanation = fuse(breakdown, weights={"a": 50, "market_structure": 50})
        assert "market_structure" in explanation
        assert "BTCUSDT" in explanation

    def test_uses_settings_weights_by_default(self):
        stats = sb.compute_universe_stats([_snap()])
        breakdown = sb.score_symbol(_snap(), stats)
        composite, coverage, _ = fuse(breakdown)  # no weights arg -> settings.RANKER_FACTOR_WEIGHTS
        assert 0.0 <= composite <= 100.0
        assert 0.0 < coverage < 1.0  # some factors unavailable by design


# ── opportunity_ranker.py ────────────────────────────────────────────────────

def _mock_scanner(snapshots: dict):
    scanner = MagicMock()
    scanner.get_snapshots.return_value = snapshots
    scanner.is_running.return_value = True
    return scanner


class TestOpportunityRanker:

    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_empty_scanner_cache_returns_empty(self):
        ranker = OpportunityRanker(_mock_scanner({}))
        assert ranker.rank() == []

    def test_ranks_highest_composite_first(self):
        snaps = {
            "GOOD": _snap(symbol="GOOD", vol=1e9, spread=0.0001, funding=0.00001),
            "BAD":  _snap(symbol="BAD",  vol=1e5, spread=0.005,  funding=0.005),
        }
        ranker = OpportunityRanker(_mock_scanner(snaps), top_n=10)
        top = ranker.rank()
        assert top[0].symbol == "GOOD"
        assert top[0].composite_score > top[1].composite_score
        assert top[0].rank == 1
        assert top[1].rank == 2

    def test_top_n_limits_output(self):
        snaps = {f"SYM{i}USDT": _snap(symbol=f"SYM{i}USDT", vol=float(i) * 1e6) for i in range(10)}
        ranker = OpportunityRanker(_mock_scanner(snaps), top_n=3)
        top = ranker.rank()
        assert len(top) == 3
        # must be the 3 highest-volume symbols (since volume dominates in this synthetic set)
        assert {o.symbol for o in top} == {"SYM9USDT", "SYM8USDT", "SYM7USDT"}

    def test_data_age_reflects_snapshot_staleness(self):
        stale = _snap(symbol="STALE", scanned_at=time.time() - 120)
        ranker = OpportunityRanker(_mock_scanner({"STALE": stale}), top_n=5)
        top = ranker.rank()
        assert top[0].data_age_s >= 119

    def test_get_latest_without_recompute(self):
        ranker = OpportunityRanker(_mock_scanner({"BTCUSDT": _snap()}), top_n=5)
        first = ranker.rank()
        again = ranker.get_latest()
        assert [o.symbol for o in again] == [o.symbol for o in first]

    def test_status_reports_expected_fields(self):
        ranker = OpportunityRanker(_mock_scanner({"BTCUSDT": _snap()}), top_n=5)
        ranker.rank()
        status = ranker.status()
        assert status["top_n"] == 5
        assert status["result_count"] == 1
        assert status["scanner_running"] is True

    def test_rank_persists_to_ranking_history(self):
        from database.db import ReadConn
        ranker = OpportunityRanker(_mock_scanner({"BTCUSDT": _snap()}), top_n=5)
        ranker.rank()
        with ReadConn(":memory:") as conn:
            row = conn.execute(
                "SELECT top_n, symbol_count FROM ranking_history ORDER BY id DESC LIMIT 1"
            ).fetchone()
        assert row is not None
        assert row["top_n"] == 1
        assert row["symbol_count"] == 1

    def test_persistence_failure_does_not_break_ranking(self, monkeypatch):
        monkeypatch.setattr(
            ranking_history, "save_ranking",
            lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
        )
        # Belt-and-suspenders: rank() wraps the persistence call in its own
        # try/except (on top of save_ranking's own internal one) so a bug
        # anywhere in the persistence path can never prevent the freshly
        # computed ranking from being returned.
        ranker = OpportunityRanker(_mock_scanner({"BTCUSDT": _snap()}), top_n=5)
        top = ranker.rank()
        assert len(top) == 1
        assert top[0].symbol == "BTCUSDT"

    def test_default_top_n_from_settings(self):
        from config.settings import settings
        ranker = OpportunityRanker(_mock_scanner({}))
        assert ranker._top_n == settings.RANKER_TOP_N


# ── ranking_history.py ───────────────────────────────────────────────────────

class TestRankingHistory:

    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def _make_ranked(self, symbol="BTCUSDT", score=80.0):
        breakdown = ScoreBreakdown(symbol=symbol, factors={
            "trend": FactorScore("trend", score, ScoreStatus.COMPUTED, "x"),
        })
        return RankedOpportunity(
            rank=1, symbol=symbol, composite_score=score, breakdown=breakdown,
            explanation="test", ranked_at=time.time(), data_age_s=1.0,
        )

    def test_save_and_get_latest_roundtrip(self):
        ranking_history.save_ranking([self._make_ranked()], symbol_count=1, duration_s=0.01)
        rows = ranking_history.get_latest_ranking(limit=1)
        assert len(rows) == 1
        assert rows[0]["data"][0]["symbol"] == "BTCUSDT"

    def test_get_latest_returns_newest_first(self):
        ranking_history.save_ranking([self._make_ranked("AAAUSDT")], symbol_count=1, duration_s=0.01)
        time.sleep(0.01)
        ranking_history.save_ranking([self._make_ranked("ZZZUSDT")], symbol_count=1, duration_s=0.01)
        rows = ranking_history.get_latest_ranking(limit=1)
        assert rows[0]["data"][0]["symbol"] == "ZZZUSDT"

    def test_avg_coverage_computed_from_breakdowns(self):
        # one fully-computed factor -> coverage 1.0 for this synthetic opportunity
        ranking_history.save_ranking([self._make_ranked()], symbol_count=1, duration_s=0.01)
        rows = ranking_history.get_latest_ranking(limit=1)
        assert rows[0]["avg_coverage"] == pytest.approx(1.0)

    def test_get_latest_ranking_limit_zero_returns_empty_list(self):
        # :memory: is a shared cached connection across tests in this run
        # (same as tests/test_market_scanner.py) — an "empty database" isn't
        # a reliably reachable state here, so this tests the one genuinely
        # deterministic empty-result case instead.
        ranking_history.save_ranking([self._make_ranked()], symbol_count=1, duration_s=0.01)
        rows = ranking_history.get_latest_ranking(limit=0)
        assert rows == []
