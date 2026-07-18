"""Unit tests for Data Layer (no live API calls)."""
import pytest

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def raw_klines():
    """Synthetic raw klines as returned by binance API."""
    rows = []
    ts = 1_700_000_000_000
    price = 50_000.0
    for i in range(5):
        close = price + i * 100
        rows.append([
            ts + i * 60_000,               # open_time
            str(close - 50),               # open
            str(close + 100),              # high
            str(close - 100),              # low
            str(close),                    # close
            str(1000.0 + i * 10),          # volume
            ts + i * 60_000 + 59_999,      # close_time
            "0", "0", "0", "0", "0",       # unused cols
        ])
    return rows


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_import_provider():
    from data.binance_provider import BinanceDataProvider
    assert BinanceDataProvider is not None


def test_klines_to_df(raw_klines):
    from data.binance_provider import BinanceDataProvider
    df = BinanceDataProvider._klines_to_df(raw_klines)

    assert list(df.columns) == ["open", "high", "low", "close", "volume"]
    assert len(df) == 5
    assert df.index.tz is not None            # UTC-aware
    assert df["close"].dtype == float


def test_klines_high_ge_low(raw_klines):
    from data.binance_provider import BinanceDataProvider
    df = BinanceDataProvider._klines_to_df(raw_klines)
    assert (df["high"] >= df["low"]).all()


def test_klines_no_nan(raw_klines):
    from data.binance_provider import BinanceDataProvider
    df = BinanceDataProvider._klines_to_df(raw_klines)
    assert not df.isnull().any().any()


# ── Clock drift correction ───────────────────────────────────────────────────
# Regression tests for: AttributeError: 'BinanceDataProvider' object has no
# attribute '_sync_time_offset' — main.py calls this every 10 cycles to
# prevent Binance -1021/-1007 errors from accumulated clock drift, but the
# method never existed. These tests cover the real fix.

@pytest.fixture
def mock_env(monkeypatch):
    """Provide dummy credentials so BinanceDataProvider.__init__ doesn't
    require real environment variables."""
    for key in (
        "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET",
    ):
        monkeypatch.setenv(key, "test")


def test_sync_time_offset_method_exists(mock_env, monkeypatch):
    """The exact regression: main.py calls dp._sync_time_offset() every
    10 cycles. It must exist and be callable."""
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": 1_700_000_000_000},
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()
    assert hasattr(dp, "_sync_time_offset")
    assert callable(dp._sync_time_offset)
    dp._sync_time_offset()   # must not raise


def test_offset_computed_for_positive_drift(mock_env, monkeypatch):
    """Server 5s ahead of local clock -> offset should be ~+5000ms."""
    import time
    real_now = int(time.time() * 1000)
    fake_server_time = real_now + 5000

    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": fake_server_time},
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    assert abs(dp._time_offset_ms_market - 5000) < 200   # allow test jitter
    assert abs(dp._time_offset_ms_trade  - 5000) < 200


def test_offset_computed_for_negative_drift(mock_env, monkeypatch):
    """Server 3s behind local clock -> offset should be ~-3000ms."""
    import time
    real_now = int(time.time() * 1000)
    fake_server_time = real_now - 3000

    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": fake_server_time},
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    assert abs(dp._time_offset_ms_market - (-3000)) < 200
    assert abs(dp._time_offset_ms_trade  - (-3000)) < 200


def test_signed_request_applies_offset(mock_env, monkeypatch):
    """The whole point of the fix: signed requests must actually use
    (local_clock + offset), not the raw local clock, or the -1021/-1007
    errors this was meant to prevent will keep happening."""
    import time
    real_now = int(time.time() * 1000)
    fake_server_time = real_now + 5000

    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": fake_server_time},
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    captured = {}

    def fake_send_request(self, method, path, payload, special):
        captured.update(payload)
        return {}

    dp.market_client.send_request = fake_send_request.__get__(dp.market_client)
    dp.market_client.sign_request("GET", "/fapi/v1/account", {})

    local_ts = int(time.time() * 1000)
    assert "timestamp" in captured
    assert "signature" in captured
    # signed timestamp should be local + ~5000ms offset, not raw local time
    assert captured["timestamp"] - local_ts > 4000


def test_sync_survives_network_failure(mock_env, monkeypatch):
    """If Binance's time endpoint is briefly unreachable, the bot must
    keep running with the previous offset, never crash."""
    def boom(self):
        raise ConnectionError("network down")

    monkeypatch.setattr("binance.um_futures.UMFutures.time", boom)
    from data.binance_provider import BinanceDataProvider

    dp = BinanceDataProvider()   # __init__ calls _sync_time_offset() internally
    assert dp._time_offset_ms_market == 0   # kept default, no crash
    dp._sync_time_offset()                   # calling again must also not raise
    assert dp._time_offset_ms_trade == 0


def test_market_and_trade_offsets_are_independent(mock_env, monkeypatch):
    """Market client (mainnet) and trade client (testnet) hit different
    servers and can drift independently — each needs its own offset."""
    import time
    real_now = int(time.time() * 1000)
    calls = {"n": 0}

    def varying_time(self):
        calls["n"] += 1
        # First call (market) drifts +5s, second call (trade) drifts -2s
        drift = 5000 if calls["n"] == 1 else -2000
        return {"serverTime": real_now + drift}

    monkeypatch.setattr("binance.um_futures.UMFutures.time", varying_time)
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()

    assert abs(dp._time_offset_ms_market - 5000) < 200
    assert abs(dp._time_offset_ms_trade  - (-2000)) < 200
    assert dp._time_offset_ms_market != dp._time_offset_ms_trade


def test_repeated_sync_calls_do_not_crash(mock_env, monkeypatch):
    """main.py calls this every 10 cycles for the lifetime of the
    process — must be safe to call repeatedly."""
    monkeypatch.setattr(
        "binance.um_futures.UMFutures.time",
        lambda self: {"serverTime": int(__import__("time").time() * 1000)},
    )
    from data.binance_provider import BinanceDataProvider
    dp = BinanceDataProvider()
    for _ in range(15):
        dp._sync_time_offset()   # simulate 15 trading cycles worth of re-syncs
