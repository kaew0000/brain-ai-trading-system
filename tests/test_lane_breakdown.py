"""tests/test_lane_breakdown.py — V16 Phase 4C, AI Self-Improvement
Governance Layer Phase 1 (docs/architecture.md §48).
"""
from __future__ import annotations

import pytest

from governance.lane_breakdown import compute_lane_breakdown

pytestmark = pytest.mark.unit


class TestComputeLaneBreakdown:

    def test_empty_rows_returns_empty_dict(self):
        assert compute_lane_breakdown([]) == {}

    def test_counts_by_lane(self):
        rows = (
            [{"execution_lane": "LIVE"}] * 3
            + [{"execution_lane": "TRAINING"}] * 2
            + [{"execution_lane": "PAPER"}]
        )
        assert compute_lane_breakdown(rows) == {"LIVE": 3, "TRAINING": 2, "PAPER": 1}

    def test_missing_execution_lane_key_counted_as_unknown(self):
        rows = [{"symbol": "BTCUSDT"}, {"execution_lane": "LIVE"}]
        result = compute_lane_breakdown(rows)
        assert result["UNKNOWN"] == 1
        assert result["LIVE"] == 1

    def test_never_fabricates_a_lane_that_did_not_appear(self):
        rows = [{"execution_lane": "LIVE"}] * 5
        result = compute_lane_breakdown(rows)
        assert "TRAINING" not in result
        assert "PAPER" not in result
