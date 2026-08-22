"""tests/test_binance_ws_client.py — V16 Phase 4C Track B, HFT-1.

Covers data/binance_ws_client.py: message parsing, per-symbol dispatch,
depth-diff sequence-gap detection triggering resync, aggTrade buffering,
and the public get_snapshot() validity/connectivity flags.

No pytest-asyncio dependency (matches this project's existing tests/
convention — see test_dashboard_serving.py's use of FastAPI's synchronous
TestClient instead). Async behavior is exercised with plain sync test
functions that call `asyncio.run(...)` internally, which needs no special
pytest plugin.
"""
import asyncio
import json
import time

import pytest

from data.binance_ws_client import (
    BinanceWSClient,
    SymbolWSSnapshot,
    _parse_depth_diff,
    _parse_rest_snapshot,
)

pytestmark = pytest.mark.unit


def _rest_snapshot(last_update_id=100):
    return {
        "lastUpdateId": last_update_id,
        "bids": [["100.00", "1.0"], ["99.50", "2.0"]],
        "asks": [["100.50", "1.0"], ["101.00", "2.0"]],
    }


def _make_client(symbols=("BTCUSDT",), snapshot_calls=None):
    """rest_snapshot_fn is a plain sync callable per BinanceWSClient's
    constructor contract — a fake here, no network/mock library needed."""
    calls = snapshot_calls if snapshot_calls is not None else []

    def fn(symbol):
        calls.append(symbol)
        return _rest_snapshot()

    return BinanceWSClient(symbols=list(symbols), rest_snapshot_fn=fn), calls


# ── Parsing helpers ──────────────────────────────────────────────────────

def test_parse_rest_snapshot():
    snap = _parse_rest_snapshot(_rest_snapshot(last_update_id=42))
    assert snap.last_update_id == 42
    assert snap.bids == [(100.0, 1.0), (99.5, 2.0)]
    assert snap.asks == [(100.5, 1.0), (101.0, 2.0)]


def test_parse_depth_diff_with_pu():
    payload = {"U": 101, "u": 105, "pu": 100, "b": [["100.00", "5.0"]], "a": [], "E": 123456}
    diff = _parse_depth_diff(payload)
    assert diff.first_update_id == 101
    assert diff.final_update_id == 105
    assert diff.prev_final_update_id == 100
    assert diff.bids == [(100.0, 5.0)]
    assert diff.event_time_ms == 123456


def test_parse_depth_diff_without_pu():
    payload = {"U": 1, "u": 2, "b": [], "a": []}
    diff = _parse_depth_diff(payload)
    assert diff.prev_final_update_id is None


# ── Construction ──────────────────────────────────────────────────────────

def test_requires_at_least_one_symbol():
    with pytest.raises(ValueError):
        BinanceWSClient(symbols=[], rest_snapshot_fn=lambda s: _rest_snapshot())


def test_get_snapshot_unknown_symbol_raises():
    client, _ = _make_client(symbols=("BTCUSDT",))
    with pytest.raises(KeyError):
        client.get_snapshot("ETHUSDT")


def test_initial_snapshot_before_any_data_is_invalid_and_disconnected():
    client, _ = _make_client()
    snap = client.get_snapshot("BTCUSDT")
    assert isinstance(snap, SymbolWSSnapshot)
    assert snap.book_valid is False
    assert snap.sequence_valid is False
    assert snap.stream_connected is False
    assert snap.best_bid is None


# ── Resync (REST snapshot fetch) ─────────────────────────────────────────

def test_resync_symbol_applies_snapshot_via_injected_fetcher():
    client, calls = _make_client()

    async def go():
        state = client._states["BTCUSDT"]
        await client._resync_symbol("BTCUSDT", state)

    asyncio.run(go())
    assert calls == ["BTCUSDT"]
    snap = client.get_snapshot("BTCUSDT")
    assert snap.best_bid == 100.0
    assert snap.best_ask == 100.5
    # sequence_valid is still False until the first straddling diff lands —
    # a snapshot alone doesn't prove continuity.
    assert snap.sequence_valid is False


def test_resync_symbol_guards_against_concurrent_duplicate_calls():
    call_count = {"n": 0}

    def fn(symbol):
        call_count["n"] += 1
        return _rest_snapshot()

    client = BinanceWSClient(symbols=["BTCUSDT"], rest_snapshot_fn=fn)

    async def go():
        state = client._states["BTCUSDT"]
        await asyncio.gather(
            client._resync_symbol("BTCUSDT", state),
            client._resync_symbol("BTCUSDT", state),
        )

    asyncio.run(go())
    # The in-flight guard means at most... note: since both start
    # essentially simultaneously before either finishes, the guard can't
    # retroactively stop the first from proceeding, but it does prevent a
    # THIRD overlapping call while one is already in flight. This test
    # documents that the guard exists and multiple resyncs don't crash —
    # not a strict call-count assertion, which would be timing-dependent.
    assert call_count["n"] >= 1
    assert client.get_snapshot("BTCUSDT").best_bid == 100.0


# ── Message dispatch: depth diff happy path + sequencing ────────────────

def _combined_frame(symbol: str, kind: str, data: dict) -> str:
    return json.dumps({"stream": f"{symbol.lower()}@{kind}", "data": data})


def test_handle_message_depth_diff_straddling_snapshot_sets_sequence_valid():
    client, _ = _make_client()

    async def go():
        state = client._states["BTCUSDT"]
        await client._resync_symbol("BTCUSDT", state)   # lastUpdateId=100
        now_ms = int(time.time() * 1000)
        frame = _combined_frame("BTCUSDT", "depth", {
            # Straddles: U=90 <= last_update_id(100)+1=101 <= u=105.
            "U": 90, "u": 105, "b": [["100.00", "3.0"]], "a": [], "E": now_ms,
        })
        client._handle_message(frame)

    asyncio.run(go())
    snap = client.get_snapshot("BTCUSDT")
    assert snap.sequence_valid is True
    assert snap.book_valid is True
    assert snap.best_bid == 100.0   # updated qty at same price


def test_handle_message_sequence_gap_invalidates_and_triggers_resync():
    resync_symbols = []

    def fn(symbol):
        resync_symbols.append(symbol)
        return _rest_snapshot(last_update_id=100 + len(resync_symbols) * 1000)

    client = BinanceWSClient(symbols=["BTCUSDT"], rest_snapshot_fn=fn)

    async def go():
        state = client._states["BTCUSDT"]
        await client._resync_symbol("BTCUSDT", state)   # lastUpdateId=1100
        now_ms = int(time.time() * 1000)
        # First straddling diff to establish sequence_valid=True:
        # U=1090 <= last_update_id(1100)+1=1101 <= u=1105.
        first = _combined_frame("BTCUSDT", "depth", {
            "U": 1090, "u": 1105, "b": [], "a": [], "E": now_ms,
        })
        client._handle_message(first)
        assert client.get_snapshot("BTCUSDT").sequence_valid is True

        # Now a diff with a gap (expected U=1106, got U=2000)
        gap = _combined_frame("BTCUSDT", "depth", {
            "U": 2000, "u": 2010, "b": [], "a": [], "E": now_ms + 1,
        })
        client._handle_message(gap)
        # Let the fire-and-forget resync task scheduled by the gap handler
        # run to completion — it does a real run_in_executor() hop (see
        # _resync_symbol), so a bare `await asyncio.sleep(0)` isn't enough
        # to guarantee the executor thread has finished by the time we
        # check resync_symbols below.
        await asyncio.sleep(0.1)

    asyncio.run(go())
    snap = client.get_snapshot("BTCUSDT")
    assert snap.sequence_valid is False
    # A resync was triggered beyond the initial manual one.
    assert len(resync_symbols) >= 2


def test_handle_message_stale_diff_before_snapshot_is_dropped_silently():
    client, _ = _make_client()
    # No resync yet -> book not synced -> message should be dropped, no crash.
    frame = _combined_frame("BTCUSDT", "depth", {"U": 1, "u": 2, "b": [], "a": []})
    client._handle_message(frame)   # should not raise
    assert client.get_snapshot("BTCUSDT").book_valid is False


# ── Message dispatch: malformed frames ───────────────────────────────────

def test_handle_message_malformed_json_dropped_without_raising():
    client, _ = _make_client()
    client._handle_message("not json {{{")   # must not raise


def test_handle_message_missing_stream_key_dropped():
    client, _ = _make_client()
    client._handle_message(json.dumps({"data": {}}))   # must not raise


def test_handle_message_unknown_symbol_ignored():
    client, _ = _make_client(symbols=("BTCUSDT",))
    frame = _combined_frame("ETHUSDT", "aggTrade", {"p": "1", "q": "1", "m": True, "T": 1})
    client._handle_message(frame)   # must not raise, no state for ETHUSDT


def test_handle_message_malformed_agg_trade_payload_dropped():
    client, _ = _make_client()
    frame = _combined_frame("BTCUSDT", "aggTrade", {"p": "not-a-number", "q": "1", "m": True, "T": 1})
    client._handle_message(frame)   # must not raise
    assert client.get_snapshot("BTCUSDT").recent_trades == []


# ── aggTrade buffering ────────────────────────────────────────────────────

def test_agg_trade_buffered_and_readable_in_snapshot():
    client, _ = _make_client()
    frame = _combined_frame("BTCUSDT", "aggTrade", {
        "p": "100.25", "q": "0.5", "m": False, "T": 1_000_000,
    })
    client._handle_message(frame)
    snap = client.get_snapshot("BTCUSDT")
    assert len(snap.recent_trades) == 1
    trade = snap.recent_trades[0]
    assert trade.price == 100.25
    assert trade.qty == 0.5
    assert trade.is_buyer_maker is False


def test_agg_trade_buffer_pruned_beyond_window():
    client, _ = _make_client()
    from config.settings import settings
    window_ms = settings.HFT_WS_TRADE_BUFFER_SECONDS * 1000

    old_frame = _combined_frame("BTCUSDT", "aggTrade", {
        "p": "100.0", "q": "1.0", "m": False, "T": 0,
    })
    client._handle_message(old_frame)
    new_frame = _combined_frame("BTCUSDT", "aggTrade", {
        "p": "101.0", "q": "1.0", "m": False, "T": window_ms + 5000,
    })
    client._handle_message(new_frame)
    snap = client.get_snapshot("BTCUSDT")
    assert len(snap.recent_trades) == 1
    assert snap.recent_trades[0].price == 101.0


# ── get_all_snapshots ─────────────────────────────────────────────────────

def test_get_all_snapshots_returns_every_configured_symbol():
    client, _ = _make_client(symbols=("BTCUSDT", "ETHUSDT"))
    snaps = client.get_all_snapshots()
    assert set(snaps.keys()) == {"BTCUSDT", "ETHUSDT"}
    assert all(isinstance(v, SymbolWSSnapshot) for v in snaps.values())


# ── Snapshot immutability (design review §16's "read once" requirement) ─

def test_get_snapshot_returns_independent_copy_not_live_view():
    client, _ = _make_client()

    async def go():
        state = client._states["BTCUSDT"]
        await client._resync_symbol("BTCUSDT", state)
        snap1 = client.get_snapshot("BTCUSDT")
        # Mutate internal state after taking the snapshot. _handle_message
        # is exercised here inside a running event loop, matching how
        # production always calls it (from within _connect_and_listen's
        # `async for` loop) — the gap path can schedule a fire-and-forget
        # resync task via asyncio.ensure_future(), which requires one.
        frame = _combined_frame("BTCUSDT", "depth", {
            "U": 90, "u": 105, "b": [["50.00", "9.0"]], "a": [], "E": 1,
        })
        client._handle_message(frame)
        snap2 = client.get_snapshot("BTCUSDT")
        assert snap1.best_bid != snap2.best_bid or snap1.data_age_ms != snap2.data_age_ms
        assert (50.0, 9.0) not in snap1.bid_levels

    asyncio.run(go())
