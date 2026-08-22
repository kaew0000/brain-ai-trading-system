"""tests/test_local_order_book.py — V16 Phase 4C Track B, HFT-1.

Covers data/local_order_book.py: snapshot application, diff application,
Binance sequence-validation rules, crossed-book detection, empty-book
handling, and staleness. Pure synchronous unit tests — no network, no
asyncio — matching this module's design (see its module docstring).
"""
import pytest

from data.local_order_book import DepthDiff, DepthSnapshot, LocalOrderBook, OrderBookError

pytestmark = pytest.mark.unit


def _snapshot(last_update_id=100, bids=None, asks=None, fetched_at_ms=1_000_000):
    return DepthSnapshot(
        last_update_id=last_update_id,
        bids=bids if bids is not None else [(100.0, 1.0), (99.5, 2.0), (99.0, 3.0)],
        asks=asks if asks is not None else [(100.5, 1.0), (101.0, 2.0), (101.5, 3.0)],
        fetched_at_ms=fetched_at_ms,
    )


def _diff(first_update_id, final_update_id, prev_final_update_id=None,
          bids=None, asks=None, event_time_ms=1_000_100):
    return DepthDiff(
        first_update_id=first_update_id,
        final_update_id=final_update_id,
        prev_final_update_id=prev_final_update_id,
        bids=bids or [],
        asks=asks or [],
        event_time_ms=event_time_ms,
    )


# ── Snapshot application ────────────────────────────────────────────────

def test_apply_snapshot_sets_synced_and_best_bid_ask():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot())
    assert book.synced is True
    assert book.best_bid() == 100.0
    assert book.best_ask() == 100.5
    assert book.last_update_id() == 100


def test_apply_snapshot_drops_zero_qty_rows():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(bids=[(100.0, 0.0), (99.0, 1.0)], asks=[(101.0, 1.0)]))
    assert book.best_bid() == 99.0


def test_empty_book_before_any_snapshot_is_invalid():
    book = LocalOrderBook("BTCUSDT")
    assert book.is_valid(max_age_ms=5000) is False
    assert book.best_bid() is None
    assert book.best_ask() is None


# ── can_apply / is_stale (pre-sequencing checks) ────────────────────────

def test_can_apply_true_when_diff_straddles_snapshot():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    # U <= L+1 <= u  ->  50 <= 101 <= 150
    assert book.can_apply(_diff(first_update_id=50, final_update_id=150)) is True


def test_can_apply_false_when_diff_is_entirely_before_snapshot():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    assert book.can_apply(_diff(first_update_id=10, final_update_id=99)) is False


def test_can_apply_false_before_any_snapshot():
    book = LocalOrderBook("BTCUSDT")
    assert book.can_apply(_diff(first_update_id=1, final_update_id=2)) is False


def test_is_stale_true_for_diff_fully_covered_by_snapshot():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    assert book.is_stale(_diff(first_update_id=50, final_update_id=100)) is True
    assert book.is_stale(_diff(first_update_id=101, final_update_id=105)) is False


# ── apply_diff: happy path ───────────────────────────────────────────────

def test_apply_diff_before_snapshot_raises():
    book = LocalOrderBook("BTCUSDT")
    with pytest.raises(OrderBookError):
        book.apply_diff(_diff(first_update_id=1, final_update_id=2))


def test_apply_diff_updates_levels_and_last_update_id():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    ok = book.apply_diff(_diff(
        first_update_id=101, final_update_id=105,
        bids=[(100.0, 5.0)], asks=[(100.5, 4.0)],
    ))
    assert ok is True
    assert book.last_update_id() == 105
    top_bids, top_asks = book.top_levels(5)
    assert top_bids[0] == (100.0, 5.0)
    assert top_asks[0] == (100.5, 4.0)


def test_apply_diff_zero_qty_removes_level():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=101, bids=[(100.0, 0.0)]))
    top_bids, _ = book.top_levels(5)
    assert 100.0 not in [p for p, _ in top_bids]
    assert book.best_bid() == 99.5   # next level down


def test_apply_diff_sequential_chain_of_updates():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    assert book.apply_diff(_diff(first_update_id=101, final_update_id=101)) is True
    assert book.apply_diff(_diff(first_update_id=102, final_update_id=104)) is True
    assert book.apply_diff(_diff(first_update_id=105, final_update_id=110)) is True
    assert book.last_update_id() == 110


def test_apply_diff_stale_diff_is_noop_true():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=105))
    # A diff fully behind current state should be a harmless no-op, not a gap.
    result = book.apply_diff(_diff(first_update_id=90, final_update_id=95))
    assert result is True
    assert book.last_update_id() == 105   # unchanged


# ── apply_diff: gap detection (the core safety property) ────────────────

def test_apply_diff_gap_invalidates_sync():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=105))
    # Next diff should start at 106, but starts at 110 -> gap.
    result = book.apply_diff(_diff(first_update_id=110, final_update_id=115))
    assert result is False
    assert book.synced is False


def test_apply_diff_pu_mismatch_invalidates_sync_even_if_u_matches():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=105))
    # U lines up (106) but pu disagrees with our last_update_id (105) ->
    # treated conservatively as a gap per this module's design.
    result = book.apply_diff(_diff(first_update_id=106, final_update_id=108, prev_final_update_id=999))
    assert result is False
    assert book.synced is False


def test_apply_diff_after_gap_requires_resync_not_further_apply():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=105))
    book.apply_diff(_diff(first_update_id=110, final_update_id=115))  # gap
    assert book.synced is False
    # A fresh snapshot resyncs cleanly.
    book.apply_snapshot(_snapshot(last_update_id=200))
    assert book.synced is True
    assert book.last_update_id() == 200


# ── Crossed book ─────────────────────────────────────────────────────────

def test_crossed_book_detected():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(
        last_update_id=100,
        bids=[(101.0, 1.0)],   # bid >= ask below -> crossed
        asks=[(100.0, 1.0)],
    ))
    assert book.is_crossed() is True
    assert book.is_valid(max_age_ms=5000, now_ms=1_000_050) is False


def test_normal_book_is_not_crossed():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot())
    assert book.is_crossed() is False


# ── Validity / staleness ─────────────────────────────────────────────────

def test_is_valid_true_for_fresh_synced_book():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(fetched_at_ms=1_000_000))
    assert book.is_valid(max_age_ms=5000, now_ms=1_000_100) is True


def test_is_valid_false_when_older_than_max_age():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(fetched_at_ms=1_000_000))
    assert book.is_valid(max_age_ms=5000, now_ms=1_010_000) is False


def test_is_valid_false_when_not_synced():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(last_update_id=100))
    book.apply_diff(_diff(first_update_id=101, final_update_id=105))
    book.apply_diff(_diff(first_update_id=999, final_update_id=1000))  # gap -> unsynced
    assert book.is_valid(max_age_ms=5000, now_ms=1_000_200) is False


def test_is_valid_false_when_one_side_empty():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(bids=[], asks=[(101.0, 1.0)], fetched_at_ms=1_000_000))
    assert book.is_valid(max_age_ms=5000, now_ms=1_000_050) is False


def test_age_ms_reflects_last_applied_update():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(fetched_at_ms=1_000_000))
    assert book.age_ms(now_ms=1_000_300) == 300
    book.apply_diff(_diff(first_update_id=101, final_update_id=101, event_time_ms=1_000_400))
    assert book.age_ms(now_ms=1_000_450) == 50


# ── top_levels ────────────────────────────────────────────────────────────

def test_top_levels_sorted_best_first_and_limited():
    book = LocalOrderBook("BTCUSDT")
    book.apply_snapshot(_snapshot(
        bids=[(99.0, 1.0), (100.0, 1.0), (99.5, 1.0)],
        asks=[(102.0, 1.0), (100.5, 1.0), (101.0, 1.0)],
    ))
    bids, asks = book.top_levels(2)
    assert [p for p, _ in bids] == [100.0, 99.5]
    assert [p for p, _ in asks] == [100.5, 101.0]
