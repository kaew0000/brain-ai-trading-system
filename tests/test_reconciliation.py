"""
tests/test_reconciliation.py

system_health/reconciliation.py had NO dedicated test coverage at all
before V16 Phase ORDER-01 (confirmed by inspection: no
test_reconciliation.py existed, and no other test module imports
ReconciliationEngine). This file covers:

  - The pre-existing _classify()/run() behavior (all-flat, all-open,
    side/quantity mismatch, presence mismatch, duplicate journal rows) —
    net-new coverage for logic that already shipped.
  - V16 Phase ORDER-01 (BUG-LIVE-ORDER-01): the actual root cause fix —
    _read_bot() previously mirrored the exchange view in live mode
    (`dict(exchange, source="exchange_mirrored")`), so a stale
    PortfolioState entry could never be detected. It now reads
    sys["portfolio_state"] independently when present, and falls back to
    the old mirrored behavior when it isn't (no regression for any
    caller that doesn't wire PortfolioState in).
  - get_last_views(): always reflects the latest run(), even while an
    unchanged mismatch is being suppressed from re-publishing.

All tests use a fresh ReconciliationEngine() instance (not the
process-wide singleton) so state never leaks between tests.
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _sys(**overrides) -> dict:
    base = {
        "data_provider":  None,
        "paper_engine":   None,
        "journal_v2":     None,
        "portfolio_state": None,
        "event_bus":      MagicMock(),
    }
    base.update(overrides)
    return base


def _dp(has_position: bool, side="LONG", qty=0.1062):
    dp = MagicMock()
    if has_position:
        dp.get_position_info.return_value = {"side": side, "positionAmt": qty}
    else:
        dp.get_position_info.return_value = None
    return dp


def _journal(open_trades=None, total_trades=0):
    jrn = MagicMock()
    jrn.get_open_trades.return_value = open_trades or []
    jrn.get_trades.return_value = [None] * total_trades
    return jrn


class TestAllFlatAndAllOpenAgree:
    def test_all_flat_no_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        result = eng.run(s)
        assert result is None
        assert eng.status()["last_result"] == "OK"

    def test_all_open_agree_no_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn)
        result = eng.run(s)
        assert result is None
        assert eng.status()["last_result"] == "OK"


class TestDuplicateJournalRows:
    def test_multiple_open_journal_rows_is_critical(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1},
                         {"id": 2, "direction": "LONG", "quantity": 0.1}], total_trades=2)
        s = _sys(data_provider=_dp(True), journal_v2=jrn)
        evt = eng.run(s)
        assert evt is not None
        assert evt.mismatch_type == "DUPLICATE_JOURNAL_TRADES"
        assert evt.severity == "critical"


class TestSideAndQuantityMismatch:
    def test_side_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([{"id": 1, "direction": "SHORT", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn)
        evt = eng.run(s)
        assert evt is not None
        assert evt.mismatch_type == "SIDE_MISMATCH"

    def test_quantity_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.5}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn)
        evt = eng.run(s)
        assert evt is not None
        assert evt.mismatch_type == "QUANTITY_MISMATCH"


class TestGhostJournalRowPresenceMismatch:
    """Pre-existing case: exchange flat, journal thinks it's still open."""

    def test_exchange_flat_journal_open_is_presence_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([{"id": 7, "direction": "LONG", "quantity": 0.1}], total_trades=3)
        s = _sys(data_provider=_dp(False), journal_v2=jrn)
        evt = eng.run(s)
        assert evt is not None
        assert evt.mismatch_type == "PRESENCE_MISMATCH"
        assert evt.severity == "critical"

    def test_startup_presence_mismatch_downgraded_to_warning(self):
        """Exchange has a pre-existing position, journal has NO trade
        history at all (total_trades == 0) — startup case, downgraded
        from critical to warning."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        jrn = _journal([], total_trades=0)
        s = _sys(data_provider=_dp(True), journal_v2=jrn)
        evt = eng.run(s)
        assert evt is not None
        assert evt.mismatch_type == "PRESENCE_MISMATCH"
        assert evt.severity == "warning"


class TestRuntimeGhostRootCause:
    """V16 Phase ORDER-01 (BUG-LIVE-ORDER-01): the actual reported bug —
    Binance flat, journal empty, but the runtime PortfolioState cache
    still reports an open position."""

    def test_bot_view_no_longer_mirrors_exchange_when_portfolio_state_present(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)

        ex = eng._read_exchange(s)
        bot = eng._read_bot(s, ex)

        assert ex["has_position"] is False
        assert bot["has_position"] is True   # independent read, NOT mirrored
        assert bot["source"] == "portfolio_state"
        assert bot["side"] == "LONG"
        assert bot["qty"] == pytest.approx(0.1062)

    def test_ghost_runtime_position_detected_as_presence_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)

        evt = eng.run(s)

        assert evt is not None
        assert evt.mismatch_type == "PRESENCE_MISMATCH"
        assert evt.bot_view["source"] == "portfolio_state"
        assert evt.bot_view["has_position"] is True
        assert evt.exchange_view["has_position"] is False

    def test_no_portfolio_state_falls_back_to_old_mirrored_behavior(self):
        """Backward compatibility: a caller that never wires in
        portfolio_state (e.g. paper mode with paper_engine absent too, or
        an existing test) gets the exact pre-Phase-ORDER-01 behavior."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))

        ex = eng._read_exchange(s)
        bot = eng._read_bot(s, ex)

        assert bot["source"] == "exchange_mirrored"
        assert bot["has_position"] == ex["has_position"]

    def test_portfolio_state_flat_agrees_no_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        ps = MagicMock()
        ps.get_position.return_value = None
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)

        result = eng.run(s)

        assert result is None
        assert eng.status()["last_result"] == "OK"


class TestGetLastViews:
    def test_none_before_any_run(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        assert eng.get_last_views() is None

    def test_reflects_latest_run_even_when_ok(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        eng.run(s)
        views = eng.get_last_views()
        assert views is not None
        assert views["mismatch_type"] is None
        assert views["exchange"]["has_position"] is False

    def test_reflects_latest_run_even_when_suppressed(self):
        """Second run() with an IDENTICAL unchanged mismatch returns None
        (suppressed, per existing _last_fired_sig behavior) but
        get_last_views() must still report the live comparison, not a
        stale pre-suppression snapshot."""
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)

        first = eng.run(s)
        second = eng.run(s)

        assert first is not None
        assert second is None  # suppressed repeat
        views = eng.get_last_views()
        assert views is not None
        assert views["mismatch_type"] == "PRESENCE_MISMATCH"

    def test_get_last_views_returns_a_copy_not_live_reference(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5))
        eng.run(s)
        views = eng.get_last_views()
        views["mismatch_type"] = "TAMPERED"
        assert eng.get_last_views()["mismatch_type"] is None


class TestInsufficientViews:
    def test_missing_data_provider_and_journal_is_no_mismatch(self):
        from system_health.reconciliation import ReconciliationEngine
        eng = ReconciliationEngine()
        s = _sys()  # no data_provider, no journal_v2, no portfolio_state
        result = eng.run(s)
        assert result is None
        views = eng.get_last_views()
        assert views["detail"] == "Insufficient verifiable views"
