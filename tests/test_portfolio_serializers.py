"""tests/test_portfolio_serializers.py — V16 Phase 2C

Pure function tests — no database, no FastAPI, no network. Every test
either passes a real portfolio_history-shaped row dict or None, mirroring
exactly what portfolio_history.get_latest_decisions()/query_decisions()
return.
"""
from __future__ import annotations

import pytest

from api.portfolio_serializers import (
    serialize_decision,
    serialize_state,
    serialize_allocations,
    serialize_sectors,
    serialize_history_entry,
    serialize_history_page,
    SOURCE_LABEL,
)

pytestmark = pytest.mark.unit


def _row(**overrides) -> dict:
    base = {
        "id": 1,
        "timestamp": "2026-07-19T00:00:00+00:00",
        "decided_at": 1750000000.0,
        "blocked": False,
        "block_reason": None,
        "selected_count": 1,
        "rejected_count": 0,
        "replacement_count": 0,
        "total_capital_allocated": 500.0,
        "total_risk_allocated": 5.0,
        "diversification_score": 100.0,
        "portfolio_score": 80.0,
        "drawdown": 0.0,
        "data": {
            "generated_at": 1750000000.0,
            "blocked": False,
            "block_reason": None,
            "selected": [{"symbol": "BTCUSDT", "capital_amount": 500.0, "priority": 1}],
            "rejected": [{"symbol": "ETHUSDT", "rank": 2, "reason": "sector_exposure_exceeded"}],
            "replacements": [],
            "sector_exposure": {"Layer1": 4000.0},
            "diversification_score": 100.0,
            "portfolio_score": 80.0,
            "total_capital_allocated": 500.0,
            "total_risk_allocated": 5.0,
            "explanation": "test",
        },
    }
    base.update(overrides)
    return base


class TestSerializeDecision:
    def test_none_row_returns_null_decision(self):
        out = serialize_decision(None)
        assert out["decision"] is None

    def test_none_row_has_source_and_live_false(self):
        out = serialize_decision(None)
        assert out["source"] == SOURCE_LABEL
        assert out["live"] is False

    def test_none_row_as_of_is_none(self):
        assert serialize_decision(None)["as_of"] is None

    def test_none_row_note_mentions_never_persisted(self):
        assert "ever been persisted" in serialize_decision(None)["note"].lower()

    def test_real_row_returns_full_data_blob(self):
        out = serialize_decision(_row())
        assert out["decision"]["selected"][0]["symbol"] == "BTCUSDT"

    def test_real_row_as_of_is_row_timestamp(self):
        out = serialize_decision(_row(timestamp="2026-01-01T00:00:00+00:00"))
        assert out["as_of"] == "2026-01-01T00:00:00+00:00"

    def test_real_row_still_marked_not_live(self):
        assert serialize_decision(_row())["live"] is False

    def test_real_row_never_fabricates_note_of_no_data(self):
        assert "never" not in serialize_decision(_row())["note"].lower()


class TestSerializeState:
    def test_none_row_positions_is_empty_list_not_null(self):
        out = serialize_state(None)
        assert out["positions"] == []

    def test_none_row_totals_are_zero_not_omitted(self):
        out = serialize_state(None)
        assert out["total_capital_allocated"] == 0.0
        assert out["total_risk_allocated"] == 0.0

    def test_none_row_blocked_is_none_not_false(self):
        # None (unknown) is distinct from False (known-not-blocked) —
        # asserting False here would fabricate a fact we don't have.
        assert serialize_state(None)["blocked"] is None

    def test_real_row_positions_from_selected(self):
        out = serialize_state(_row())
        assert out["positions"][0]["symbol"] == "BTCUSDT"

    def test_real_row_totals_from_row_not_from_data_blob(self):
        out = serialize_state(_row(total_capital_allocated=999.0))
        assert out["total_capital_allocated"] == 999.0

    def test_real_row_blocked_reflects_row(self):
        out = serialize_state(_row(blocked=True, block_reason="daily loss limit"))
        assert out["blocked"] is True
        assert out["block_reason"] == "daily loss limit"

    def test_state_payload_never_uses_word_live_true(self):
        assert serialize_state(_row())["live"] is False


class TestSerializeAllocations:
    def test_none_row_returns_empty_list(self):
        assert serialize_allocations(None)["allocations"] == []

    def test_real_row_returns_selected_list(self):
        out = serialize_allocations(_row())
        assert len(out["allocations"]) == 1
        assert out["allocations"][0]["symbol"] == "BTCUSDT"

    def test_allocations_excludes_rejected(self):
        out = serialize_allocations(_row())
        symbols = [a["symbol"] for a in out["allocations"]]
        assert "ETHUSDT" not in symbols


class TestSerializeSectors:
    def test_none_row_empty_exposure_and_null_score(self):
        out = serialize_sectors(None)
        assert out["sector_exposure"] == {}
        assert out["diversification_score"] is None

    def test_real_row_returns_sector_exposure(self):
        out = serialize_sectors(_row())
        assert out["sector_exposure"] == {"Layer1": 4000.0}

    def test_real_row_returns_diversification_score_from_row_column(self):
        out = serialize_sectors(_row(diversification_score=42.0))
        assert out["diversification_score"] == 42.0


class TestSerializeHistoryEntry:
    def test_condensed_entry_has_no_full_data_blob(self):
        entry = serialize_history_entry(_row())
        assert "data" not in entry

    def test_condensed_entry_includes_counts(self):
        entry = serialize_history_entry(_row(selected_count=3, rejected_count=1))
        assert entry["selected_count"] == 3
        assert entry["rejected_count"] == 1

    def test_condensed_entry_symbols_derived_from_selected(self):
        entry = serialize_history_entry(_row())
        assert entry["symbols"] == ["BTCUSDT"]

    def test_condensed_entry_symbols_sorted_and_deduped(self):
        row = _row()
        row["data"] = dict(row["data"])
        row["data"]["selected"] = [
            {"symbol": "ZZZUSDT"}, {"symbol": "AAAUSDT"}, {"symbol": "ZZZUSDT"},
        ]
        entry = serialize_history_entry(row)
        assert entry["symbols"] == ["AAAUSDT", "ZZZUSDT"]


class TestSerializeHistoryPage:
    def test_empty_rows_and_zero_total(self):
        out = serialize_history_page([], total=0, limit=50, offset=0)
        assert out["entries"] == []
        assert out["pagination"]["total"] == 0
        assert out["pagination"]["has_more"] is False

    def test_pagination_has_more_true_when_more_rows_exist(self):
        out = serialize_history_page([_row()], total=5, limit=1, offset=0)
        assert out["pagination"]["has_more"] is True

    def test_pagination_has_more_false_at_end(self):
        out = serialize_history_page([_row()], total=1, limit=50, offset=0)
        assert out["pagination"]["has_more"] is False

    def test_pagination_returned_reflects_actual_row_count(self):
        out = serialize_history_page([_row(), _row(id=2)], total=2, limit=50, offset=0)
        assert out["pagination"]["returned"] == 2

    def test_filtered_total_none_is_preserved_not_coerced_to_zero(self):
        out = serialize_history_page([_row()], total=None, limit=50, offset=0)
        assert out["pagination"]["total"] is None

    def test_filtered_has_more_true_when_full_page_returned(self):
        rows = [_row(id=i) for i in range(5)]
        out = serialize_history_page(rows, total=None, limit=5, offset=0)
        assert out["pagination"]["has_more"] is True

    def test_filtered_has_more_false_when_partial_page_returned(self):
        rows = [_row(id=i) for i in range(3)]
        out = serialize_history_page(rows, total=None, limit=5, offset=0)
        assert out["pagination"]["has_more"] is False

    def test_offset_reflected_in_pagination(self):
        out = serialize_history_page([_row()], total=10, limit=1, offset=4)
        assert out["pagination"]["offset"] == 4
