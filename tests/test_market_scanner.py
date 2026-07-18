"""
tests/test_market_scanner.py

V16 Phase 2, Part 1 — Market Scanner tests. Every Binance response is
mocked, shaped exactly like Binance's documented Futures REST API (no
live network calls — this sandbox has no route to api.binance.com
anyway, and tests must stay hermetic regardless).
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from scanner.market_scanner import (
    MarketScanner, SymbolSnapshot, _safe_float, _atr_pct_from_klines,
)

pytestmark = pytest.mark.unit


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_scanner_breaker():
    from scanner.market_scanner import _SCANNER_BREAKER
    _SCANNER_BREAKER.reset()
    yield
    _SCANNER_BREAKER.reset()


def _mock_exchange_info():
    return {
        "symbols": [
            {"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            {"symbol": "ETHUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            {"symbol": "SOLUSDT", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
            # excluded: not USDT-margined
            {"symbol": "BTCUSD_PERP", "status": "TRADING", "contractType": "PERPETUAL", "quoteAsset": "USD"},
            # excluded: not a perpetual
            {"symbol": "BTCUSDT_240329", "status": "TRADING", "contractType": "CURRENT_QUARTER", "quoteAsset": "USDT"},
            # excluded: delisted
            {"symbol": "DEADUSDT", "status": "BREAK", "contractType": "PERPETUAL", "quoteAsset": "USDT"},
        ]
    }


def _mock_ticker_24hr():
    return [
        {"symbol": "BTCUSDT", "lastPrice": "65000.0", "priceChangePercent": "2.5", "quoteVolume": "500000000"},
        {"symbol": "ETHUSDT", "lastPrice": "3400.0", "priceChangePercent": "-1.2", "quoteVolume": "200000000"},
        {"symbol": "SOLUSDT", "lastPrice": "150.0", "priceChangePercent": "5.0", "quoteVolume": "500000"},
    ]


def _mock_mark_price():
    return [
        {"symbol": "BTCUSDT", "markPrice": "65010.0", "lastFundingRate": "0.0001"},
        {"symbol": "ETHUSDT", "markPrice": "3401.0", "lastFundingRate": "-0.0002"},
        {"symbol": "SOLUSDT", "markPrice": "150.2", "lastFundingRate": "0.0005"},
    ]


def _mock_book_ticker():
    return [
        {"symbol": "BTCUSDT", "bidPrice": "64995.0", "askPrice": "65005.0"},
        {"symbol": "ETHUSDT", "bidPrice": "3399.0", "askPrice": "3403.0"},
        {"symbol": "SOLUSDT", "bidPrice": "150.0", "askPrice": "150.4"},
    ]


def _mock_klines(n=20, start=100.0):
    """Shaped like raw Binance klines: 12-field lists."""
    out = []
    price = start
    for i in range(n):
        o, h, l, c = price, price * 1.01, price * 0.99, price * 1.002
        out.append([
            1700000000000 + i * 900000, str(o), str(h), str(l), str(c), "1000",
            1700000899999 + i * 900000, "100000", 500, "500", "50000", "0",
        ])
        price = c
    return out


def _mock_open_interest(value="12345.6"):
    return {"openInterest": value, "symbol": "BTCUSDT"}


def _make_client(exchange_info=None, ticker=None, mark=None, book=None, klines=None, oi=None):
    client = MagicMock()
    client.exchange_info.return_value = exchange_info if exchange_info is not None else _mock_exchange_info()
    client.ticker_24hr_price_change.return_value = ticker if ticker is not None else _mock_ticker_24hr()
    client.mark_price.return_value = mark if mark is not None else _mock_mark_price()
    client.book_ticker.return_value = book if book is not None else _mock_book_ticker()
    client.klines.return_value = klines if klines is not None else _mock_klines()
    client.open_interest.return_value = oi if oi is not None else _mock_open_interest()
    return client


def _make_scanner(client=None, **kwargs):
    dp = MagicMock()
    dp.market_client = client or _make_client()
    kwargs.setdefault("interval_s", 20)
    kwargs.setdefault("detail_top_n", 2)
    kwargs.setdefault("min_quote_volume", 1_000_000.0)
    kwargs.setdefault("universe_refresh_s", 3600)
    return MarketScanner(dp, **kwargs)


# ── Helpers ──────────────────────────────────────────────────────────────────

class TestSafeFloat:
    def test_valid_string(self):
        assert _safe_float("1.5") == 1.5

    def test_none_returns_default(self):
        assert _safe_float(None) == 0.0
        assert _safe_float(None, default=-1.0) == -1.0

    def test_invalid_string_returns_default(self):
        assert _safe_float("not-a-number") == 0.0

    def test_int_input(self):
        assert _safe_float(5) == 5.0


class TestAtrPctFromKlines:
    def test_valid_klines_produces_positive_float(self):
        atr = _atr_pct_from_klines(_mock_klines(30))
        assert atr is not None
        assert atr > 0

    def test_empty_klines_returns_none(self):
        assert _atr_pct_from_klines([]) is None

    def test_too_short_returns_none(self):
        assert _atr_pct_from_klines(_mock_klines(1)) is None

    def test_malformed_data_returns_none_not_raise(self):
        assert _atr_pct_from_klines([["bad", "data"]]) is None


class TestSymbolSnapshot:
    def test_to_dict_round_trips(self):
        snap = SymbolSnapshot(
            symbol="BTCUSDT", price=65000.0, price_change_pct_24h=1.0,
            quote_volume_24h=1e9, funding_rate=0.0001, spread_pct=0.0001,
            open_interest=1000.0, atr_pct=0.01, scanned_at=time.time(), detail_at=None,
        )
        d = snap.to_dict()
        assert d["symbol"] == "BTCUSDT"
        assert d["open_interest"] == 1000.0


# ── Construction ─────────────────────────────────────────────────────────────

class TestConstruction:
    def test_defaults_pulled_from_settings(self):
        from config.settings import settings
        dp = MagicMock()
        dp.market_client = _make_client()
        scanner = MarketScanner(dp)
        assert scanner._interval == settings.SCANNER_INTERVAL_SECONDS
        assert scanner._detail_top_n == settings.SCANNER_DETAIL_TOP_N

    def test_explicit_overrides_respected(self):
        scanner = _make_scanner(interval_s=5, detail_top_n=1)
        assert scanner._interval == 5
        assert scanner._detail_top_n == 1

    def test_not_running_before_start(self):
        scanner = _make_scanner()
        assert scanner.is_running() is False


# ── Universe ─────────────────────────────────────────────────────────────────

class TestUniverse:
    def test_filters_to_usdt_perpetual_trading_only(self):
        scanner = _make_scanner()
        universe = scanner._fetch_universe()
        assert set(universe) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}

    def test_raises_on_zero_eligible_symbols(self):
        client = _make_client(exchange_info={"symbols": []})
        scanner = _make_scanner(client=client)
        with pytest.raises(ValueError):
            scanner._fetch_universe()

    def test_stale_universe_kept_on_refresh_failure(self):
        scanner = _make_scanner()
        scanner._universe = ["BTCUSDT"]
        scanner._universe_refreshed_at = time.time()
        scanner._client.exchange_info.side_effect = Exception("network down")
        # forces a refresh attempt despite recency, to exercise the fallback path
        scanner._universe_refresh_s = 0
        scanner._maybe_refresh_universe()
        assert scanner._universe == ["BTCUSDT"]  # kept, not wiped


# ── Bulk pass ────────────────────────────────────────────────────────────────

class TestBulkFetch:
    def test_merges_all_three_sources(self):
        scanner = _make_scanner()
        scanner._universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        bulk = scanner._fetch_bulk()
        assert bulk["BTCUSDT"]["price"] == 65010.0  # mark price preferred over lastPrice
        assert bulk["BTCUSDT"]["funding_rate"] == 0.0001
        assert bulk["BTCUSDT"]["quote_volume_24h"] == 500000000.0

    def test_spread_computed_correctly(self):
        scanner = _make_scanner()
        scanner._universe = ["BTCUSDT"]
        bulk = scanner._fetch_bulk()
        expected = (65005.0 - 64995.0) / 65010.0
        assert bulk["BTCUSDT"]["spread_pct"] == pytest.approx(expected, rel=1e-6)

    def test_symbols_outside_universe_excluded(self):
        client = _make_client(ticker=_mock_ticker_24hr() + [
            {"symbol": "NOTUSDT", "lastPrice": "1", "priceChangePercent": "0", "quoteVolume": "1"}
        ])
        scanner = _make_scanner(client=client)
        scanner._universe = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]
        bulk = scanner._fetch_bulk()
        assert "NOTUSDT" not in bulk

    def test_symbol_with_no_price_anywhere_is_skipped(self):
        client = _make_client(
            ticker=[{"symbol": "BTCUSDT", "lastPrice": None, "priceChangePercent": "0", "quoteVolume": "1"}],
            mark=[{"symbol": "BTCUSDT", "markPrice": None, "lastFundingRate": "0"}],
        )
        scanner = _make_scanner(client=client)
        scanner._universe = ["BTCUSDT"]
        bulk = scanner._fetch_bulk()
        assert "BTCUSDT" not in bulk


# ── Candidate selection ──────────────────────────────────────────────────────

class TestCandidateSelection:
    def test_respects_min_quote_volume_floor(self):
        scanner = _make_scanner(min_quote_volume=1_000_000.0, detail_top_n=10)
        bulk = {
            "BTCUSDT": {"quote_volume_24h": 5e8},
            "SOLUSDT": {"quote_volume_24h": 5e5},  # below floor
        }
        candidates = scanner._select_detail_candidates(bulk)
        assert candidates == ["BTCUSDT"]

    def test_respects_top_n_limit_sorted_by_volume(self):
        scanner = _make_scanner(min_quote_volume=0.0, detail_top_n=2)
        bulk = {
            "A": {"quote_volume_24h": 100},
            "B": {"quote_volume_24h": 300},
            "C": {"quote_volume_24h": 200},
        }
        candidates = scanner._select_detail_candidates(bulk)
        assert candidates == ["B", "C"]


# ── Detail pass ──────────────────────────────────────────────────────────────

class TestDetailFetch:
    def test_detail_returns_atr_and_oi(self):
        scanner = _make_scanner()
        details = scanner._fetch_details(["BTCUSDT"])
        assert "BTCUSDT" in details
        assert details["BTCUSDT"]["atr_pct"] is not None
        assert details["BTCUSDT"]["open_interest"] == 12345.6

    def test_one_symbol_failure_does_not_abort_batch(self):
        client = _make_client()

        def flaky_klines(symbol, interval, limit):
            if symbol == "ETHUSDT":
                raise Exception("boom")
            return _mock_klines()
        client.klines.side_effect = flaky_klines

        scanner = _make_scanner(client=client)
        details = scanner._fetch_details(["BTCUSDT", "ETHUSDT", "SOLUSDT"])
        assert "BTCUSDT" in details
        assert "ETHUSDT" not in details
        assert "SOLUSDT" in details


# ── Merge (stale-detail retention) ──────────────────────────────────────────

class TestMerge:
    def test_new_detail_overwrites(self):
        scanner = _make_scanner()
        bulk = {"BTCUSDT": {"price": 1, "price_change_pct_24h": 0, "quote_volume_24h": 0,
                             "funding_rate": 0, "spread_pct": 0}}
        details = {"BTCUSDT": {"atr_pct": 0.02, "open_interest": 999}}
        merged = scanner._merge(bulk, details)
        assert merged["BTCUSDT"].atr_pct == 0.02
        assert merged["BTCUSDT"].detail_at is not None

    def test_missing_detail_falls_back_to_previous_cycle(self):
        scanner = _make_scanner()
        scanner._snapshots = {
            "BTCUSDT": SymbolSnapshot(
                symbol="BTCUSDT", price=1, price_change_pct_24h=0, quote_volume_24h=0,
                funding_rate=0, spread_pct=0, open_interest=555.0, atr_pct=0.03,
                scanned_at=time.time() - 100, detail_at=time.time() - 100,
            )
        }
        bulk = {"BTCUSDT": {"price": 2, "price_change_pct_24h": 0, "quote_volume_24h": 0,
                             "funding_rate": 0, "spread_pct": 0}}
        merged = scanner._merge(bulk, {})  # no detail this cycle
        assert merged["BTCUSDT"].open_interest == 555.0
        assert merged["BTCUSDT"].atr_pct == 0.03

    def test_brand_new_symbol_with_no_detail_is_none(self):
        scanner = _make_scanner()
        bulk = {"NEWUSDT": {"price": 1, "price_change_pct_24h": 0, "quote_volume_24h": 0,
                             "funding_rate": 0, "spread_pct": 0}}
        merged = scanner._merge(bulk, {})
        assert merged["NEWUSDT"].open_interest is None
        assert merged["NEWUSDT"].atr_pct is None


# ── End-to-end cycle ─────────────────────────────────────────────────────────

class TestRunCycle:
    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_full_cycle_populates_snapshots(self):
        scanner = _make_scanner(detail_top_n=3, min_quote_volume=0.0)
        merged = scanner.run_cycle()
        assert set(merged.keys()) == {"BTCUSDT", "ETHUSDT", "SOLUSDT"}
        assert scanner.get_snapshots() == merged

    def test_cycle_persists_a_row(self):
        from database.db import ReadConn
        scanner = _make_scanner(detail_top_n=3, min_quote_volume=0.0)
        scanner.run_cycle()
        with ReadConn(":memory:") as conn:
            row = conn.execute("SELECT symbol_count FROM scanner_snapshots ORDER BY id DESC LIMIT 1").fetchone()
        assert row is not None
        assert row["symbol_count"] == 3

    def test_bulk_failure_leaves_prior_snapshots_intact(self):
        scanner = _make_scanner(detail_top_n=3, min_quote_volume=0.0)
        scanner.run_cycle()
        first = scanner.get_snapshots()

        scanner._client.ticker_24hr_price_change.side_effect = Exception("down")
        with pytest.raises(Exception):
            scanner.run_cycle()
        assert scanner.get_snapshots() == first  # unchanged, not wiped

    def test_status_reflects_cycle_count(self):
        scanner = _make_scanner(detail_top_n=3, min_quote_volume=0.0)
        assert scanner.status()["cycle_count"] == 0
        scanner.run_cycle()
        assert scanner.status()["cycle_count"] == 1


# ── Lifecycle (thread) ───────────────────────────────────────────────────────

class TestLifecycle:
    @pytest.fixture(autouse=True)
    def _memory_db(self, monkeypatch):
        from config.settings import settings
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        yield

    def test_start_stop(self):
        scanner = _make_scanner(interval_s=1, detail_top_n=3, min_quote_volume=0.0)
        scanner.start()
        try:
            assert scanner.is_running() is True
            time.sleep(0.3)
            assert scanner.get_snapshots()  # at least one cycle completed
        finally:
            scanner.stop()
        assert scanner.is_running() is False

    def test_double_start_does_not_spawn_second_thread(self):
        scanner = _make_scanner(interval_s=1, detail_top_n=3, min_quote_volume=0.0)
        scanner.start()
        try:
            first_thread = scanner._thread
            scanner.start()
            assert scanner._thread is first_thread
        finally:
            scanner.stop()


# ── Retention ────────────────────────────────────────────────────────────────

class TestPruning:
    def test_prune_removes_old_rows_keeps_recent(self, monkeypatch):
        from config.settings import settings
        from database.db import ManagedConn, ReadConn
        monkeypatch.setattr(settings, "DATABASE_PATH", ":memory:")
        monkeypatch.setattr(settings, "SCANNER_SNAPSHOT_RETENTION_HOURS", 1)

        scanner = _make_scanner()
        old_ts = time.time() - 7200  # 2h old, outside 1h retention
        new_ts = time.time()
        with ManagedConn(":memory:") as conn:
            conn.execute(
                "INSERT INTO scanner_snapshots (timestamp, scanned_at, symbol_count, detail_count, "
                "cycle_duration_s, data) VALUES (?,?,?,?,?,?)",
                ("old", old_ts, 1, 0, 0.0, "{}"),
            )
            conn.execute(
                "INSERT INTO scanner_snapshots (timestamp, scanned_at, symbol_count, detail_count, "
                "cycle_duration_s, data) VALUES (?,?,?,?,?,?)",
                ("new", new_ts, 1, 0, 0.0, "{}"),
            )
            conn.commit()

        scanner._prune_old_snapshots()

        with ReadConn(":memory:") as conn:
            rows = conn.execute("SELECT timestamp FROM scanner_snapshots").fetchall()
        timestamps = {r["timestamp"] for r in rows}
        assert "old" not in timestamps
        assert "new" in timestamps


# ── Settings defaults ────────────────────────────────────────────────────────

class TestSettingsDefaults:
    def test_scanner_disabled_by_default(self):
        from config.settings import Settings
        assert Settings().SCANNER_ENABLED is False

    def test_default_interval_is_20s(self):
        from config.settings import Settings
        assert Settings().SCANNER_INTERVAL_SECONDS == 20
