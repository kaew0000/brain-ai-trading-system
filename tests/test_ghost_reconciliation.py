"""
tests/test_ghost_reconciliation.py

Track C3 Phase 2: system_health/ghost_reconciliation.py —
GhostReconciliationMonitor, composed on top of OrderStateManager (V16
Phase ORDER-01) + OrderTimeline (Track C3 Phase 1). See that module's
docstring for the full composition rationale (why this is additive, not
a duplicate of order_state.py's own GHOST/DESYNC classification).

Exercises GhostReconciliationMonitor against REAL OrderStateManager +
ReconciliationEngine instances (not mocks) so the classification tests
are honest about what the existing, unchanged reconciliation pipeline
actually returns — only data_provider/journal/portfolio_state/
trade_lifecycle/order_timeline/event_bus are mocked. Every test uses
fresh instances of everything, and resets the process-wide
RecoveryEngine singleton (system_health.reconciliation.
ReconciliationEngine.run() always calls system_health.recovery_engine.
get_recovery_engine() — the GLOBAL singleton, not anything passed via
`sys` — see recovery_engine.py's RecoveryEngine._orphan_hold, which
must not leak between tests).
"""
from __future__ import annotations

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from system_health.order_state import OrderStateManager
from system_health.reconciliation import ReconciliationEngine
from system_health.recovery_engine import reset_recovery_engine
from system_health.ghost_reconciliation import (
    DetectionStatus,
    GhostReconciliationMonitor,
)

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_global_recovery_engine():
    """The reconciliation pipeline this module sits on top of always
    routes recovery through the process-wide RecoveryEngine singleton
    (see system_health/reconciliation.py run()'s
    `from system_health.recovery_engine import get_recovery_engine`) —
    never through anything passed in `sys`. Reset it around every test
    so RecoveryEngine._orphan_hold (V16 BUG-LIVE-RISK-02) never leaks
    across test cases in the same pytest process."""
    reset_recovery_engine()
    yield
    reset_recovery_engine()


@dataclass
class _FakePortfolioPosition:
    direction: str
    quantity: float


def _dp(has_position: bool, side="LONG", qty=0.1):
    dp = MagicMock()
    dp.get_position_info.return_value = (
        {"side": side, "positionAmt": qty} if has_position else None
    )
    return dp


def _journal(open_trades=None, total_trades=0):
    jrn = MagicMock()
    jrn.get_open_trades.return_value = open_trades or []
    jrn.get_trades.return_value = [None] * total_trades
    return jrn


def _timeline(symbol: str, state: str | None):
    tl = MagicMock()
    tl.current_state.return_value = {"symbol": symbol, "state": state}
    tl.recent.return_value = (
        [{"symbol": symbol, "state_after": state, "timestamp": "2026-08-07T00:00:00+00:00"}]
        if state else []
    )
    return tl


def _sys(**overrides) -> dict:
    base = {
        "data_provider":        None,
        "paper_engine":          None,
        "journal_v2":            None,
        "portfolio_state":       None,
        "trade_lifecycle":       None,
        "order_timeline":        None,
        "event_bus":             MagicMock(),
        "reconciliation_engine": ReconciliationEngine(),
        "order_state_manager":   OrderStateManager(),
    }
    base.update(overrides)
    return base


SYMBOL = "BTCUSDT"


# ── A. Clean state ──────────────────────────────────────────────────────

class TestRealPosition:
    def test_all_agree_open_with_active_timeline_is_real_position(self):
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, "LONG", 0.1), journal_v2=jrn,
                  order_timeline=_timeline(SYMBOL, "OPEN"))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.REAL_POSITION.value
        assert result.timeline_desync is False


# ── B. Ghost runtime ─────────────────────────────────────────────────────

class TestGhostRuntime:
    def test_stale_portfolio_state_is_ghost_runtime(self):
        """Exchange FLAT, Runtime LONG (stale PortfolioState), Journal
        CLOSED/EMPTY, Timeline CLOSED -> GHOST_RUNTIME."""
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, order_timeline=_timeline(SYMBOL, "CLOSED"))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.GHOST_RUNTIME.value
        assert result.severity == "critical"
        assert result.ghost_detected is True
        assert result.mismatch_type == "PRESENCE_MISMATCH"
        assert result.timeline_desync is False  # CLOSED is not an active state


class TestGhostJournal:
    def test_stale_journal_row_with_no_independent_runtime_is_ghost_journal(self):
        """Exchange FLAT, journal still has an OPEN trade, no
        independent runtime source (portfolio_state=None -> bot mirrors
        exchange, per reconciliation.py's own documented fallback)."""
        jrn = _journal([{"id": 7, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(False), journal_v2=jrn, portfolio_state=None)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.GHOST_JOURNAL.value
        assert result.severity == "critical"


# ── C. Orphan exchange ───────────────────────────────────────────────────

class TestOrphanExchange:
    def test_real_exchange_position_nothing_else_knows_is_orphan_exchange(self):
        s = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.ORPHAN_EXCHANGE.value
        assert result.severity == "critical"
        assert result.ghost_detected is False

    def test_orphan_exchange_never_produces_a_close_order_result(self):
        """Real-money safety: the only automatic action this whole
        pipeline can take for an orphaned exchange position is
        protective-SL-and-hold (system_health/recovery_engine.py
        ._protect_orphaned_exchange_position) — never a close. Assert
        the recovery_result the pipeline actually returned never
        indicates a close, and that the mock data_provider was never
        asked to place a market/close order (only get_position_info /
        get_account_balance, which _protect_orphaned_exchange_position
        legitimately calls)."""
        dp = _dp(True)
        s = _sys(data_provider=dp, journal_v2=_journal([], total_trades=0))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.recovery_result is not None
        assert "close" not in result.recovery_result.lower()
        for call in dp.method_calls:
            assert call[0] not in ("close_position", "market_close", "place_market_order")


# ── D. Side mismatch / E. Quantity mismatch ──────────────────────────────

class TestSideAndQuantityMismatch:
    def test_side_mismatch(self):
        jrn = _journal([{"id": 1, "direction": "SHORT", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.SIDE_MISMATCH.value
        assert result.severity == "critical"

    def test_quantity_mismatch(self):
        jrn = _journal([{"id": 1, "direction": "LONG", "quantity": 0.5}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=1.0), journal_v2=jrn)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.QUANTITY_MISMATCH.value
        assert result.severity == "warning"


# ── F. Timeline desync ───────────────────────────────────────────────────

class TestTimelineDesync:
    def test_exchange_flat_but_timeline_still_open_is_timeline_desync(self):
        """Every OTHER source agrees flat (no ghost/desync via the
        existing pipeline at all) — only OrderTimeline's last recorded
        state still looks active. This is the one condition nothing in
        the codebase could detect before this phase."""
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_timeline=_timeline(SYMBOL, "OPEN"))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.TIMELINE_DESYNC.value
        assert result.timeline_desync is True
        assert result.timeline_state == "OPEN"
        assert result.severity == "warning"

    def test_exchange_flat_timeline_closed_is_not_desync(self):
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_timeline=_timeline(SYMBOL, "CLOSED"))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.NO_POSITION.value
        assert result.timeline_desync is False

    def test_no_order_timeline_available_never_flags_desync(self):
        """OrderTimeline is off by default (settings.ORDER_TIMELINE_
        ENABLED=False in production) — absence must degrade gracefully,
        never produce a false positive."""
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_timeline=None)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.timeline_desync is False
        assert result.timeline_state is None

    def test_timeline_read_failure_is_non_fatal(self):
        tl = MagicMock()
        tl.current_state.side_effect = RuntimeError("boom")
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3), order_timeline=tl)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.NO_POSITION.value
        assert result.timeline_desync is False


# ── G. Recovery (observation only — no new recovery action) ─────────────

class TestRecoveryObservation:
    def test_proven_ghost_runtime_gets_cleared_by_existing_recovery_engine(self):
        """GhostReconciliationMonitor invents no recovery of its own —
        this confirms the EXISTING pipeline it sits on top of still
        clears a proven ghost runtime position end-to-end through this
        new layer, and that the monitor correctly observes it."""
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        ps.remove_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.GHOST_RUNTIME.value
        assert result.recovery_attempted is True
        ps.remove_position.assert_called_once()

    def test_real_orphan_recovery_never_closes_exchange_position(self):
        s = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.ORPHAN_EXCHANGE.value
        assert result.recovery_result != "orphan_closed"
        assert "close" not in (result.recovery_result or "").lower()


# ── H. Event deduplication ────────────────────────────────────────────────

class TestEventDeduplication:
    def test_repeated_identical_timeline_desync_does_not_republish(self):
        bus = MagicMock()
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_timeline=_timeline(SYMBOL, "OPEN"), event_bus=bus)
        mon = GhostReconciliationMonitor()

        first = mon.check(s, symbol=SYMBOL)
        assert first.status == DetectionStatus.TIMELINE_DESYNC.value
        first_events = [c.args[1] for c in bus.publish.call_args_list]
        assert "ORDER_TIMELINE_DESYNC" in first_events
        bus.publish.reset_mock()

        second = mon.check(s, symbol=SYMBOL)
        third = mon.check(s, symbol=SYMBOL)
        assert second.status == DetectionStatus.TIMELINE_DESYNC.value
        assert third.status == DetectionStatus.TIMELINE_DESYNC.value
        bus.publish.assert_not_called()

    def test_repeated_identical_side_mismatch_does_not_republish(self):
        bus = MagicMock()
        jrn = _journal([{"id": 1, "direction": "SHORT", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn, event_bus=bus)
        mon = GhostReconciliationMonitor()

        mon.check(s, symbol=SYMBOL)
        assert "RUNTIME_POSITION_MISMATCH" in [c.args[1] for c in bus.publish.call_args_list]
        bus.publish.reset_mock()

        mon.check(s, symbol=SYMBOL)
        mon.check(s, symbol=SYMBOL)
        bus.publish.assert_not_called()

    def test_transition_away_and_back_does_not_republish_within_dedup_window(self):
        """A-> B -> A within the same polling burst should not re-fire
        A's event a second time inside ORDER_RECONCILIATION_DEDUP_SECONDS,
        even though A->B->A are three distinct transitions."""
        bus = MagicMock()
        jrn_mismatch = _journal([{"id": 1, "direction": "SHORT", "quantity": 0.1}], total_trades=1)
        jrn_clean = _journal([{"id": 1, "direction": "LONG", "quantity": 0.1}], total_trades=1)
        s = _sys(data_provider=_dp(True, side="LONG", qty=0.1), journal_v2=jrn_mismatch, event_bus=bus)
        mon = GhostReconciliationMonitor()

        mon.check(s, symbol=SYMBOL)  # -> SIDE_MISMATCH, publishes
        bus.publish.reset_mock()

        s["journal_v2"] = jrn_clean
        mon.check(s, symbol=SYMBOL)  # -> REAL_POSITION

        s["journal_v2"] = jrn_mismatch
        mon.check(s, symbol=SYMBOL)  # -> SIDE_MISMATCH again, but inside dedup window

        assert "RUNTIME_POSITION_MISMATCH" not in [c.args[1] for c in bus.publish.call_args_list]

    def test_no_event_bus_does_not_crash(self):
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_timeline=_timeline(SYMBOL, "OPEN"), event_bus=None)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.TIMELINE_DESYNC.value

    def test_ghost_and_orphan_do_not_duplicate_existing_order_state_events(self):
        """Per the module's own 'reuse first' rule: GHOST_RUNTIME/
        GHOST_JOURNAL/ORPHAN_EXCHANGE findings must NOT get a second,
        duplicate event from this layer — OrderStateManager already
        published GHOST_POSITION_DETECTED/POSITION_DESYNC for them."""
        bus = MagicMock()
        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5),
                  portfolio_state=ps, event_bus=bus)
        GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        published = [c.args[1] for c in bus.publish.call_args_list]
        assert "GHOST_DETECTED" not in published
        assert "RUNTIME_POSITION_MISMATCH" not in published


# ── Metrics ────────────────────────────────────────────────────────────

class TestMetrics:
    def test_counters_use_the_brief_requested_names_and_accumulate(self):
        mon = GhostReconciliationMonitor()

        s_flat = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3))
        mon.check(s_flat, symbol=SYMBOL)

        ps = MagicMock()
        ps.get_position.return_value = _FakePortfolioPosition("LONG", 0.1062)
        s_ghost = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=5), portfolio_state=ps)
        mon.check(s_ghost, symbol="ETHUSDT")

        s_orphan = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))
        mon.check(s_orphan, symbol="SOLUSDT")

        status = mon.status()
        for field in (
            "reconciliation_count", "ghost_detected_count", "runtime_mismatch_count",
            "orphan_exchange_count", "recovery_success_count", "recovery_failure_count",
            "timeline_desync_count", "last_reconciliation_timestamp", "last_recovery_timestamp",
            "reconciliation_latency_ms", "timeline_sync_latency_ms",
        ):
            assert field in status

        assert status["reconciliation_count"] == 3
        assert status["ghost_detected_count"] >= 1
        assert status["orphan_exchange_count"] >= 1
        assert status["last_reconciliation_timestamp"] is not None

    def test_metrics_are_independent_of_order_state_manager_counters(self):
        """C3-2's counters must be additive, not a rename/replacement of
        OrderStateManager.status()'s own (sync_count/desync_count/
        ghost_count/recovery_count) — different names, different
        instances, both remain independently correct."""
        from system_health.order_state import get_order_state_manager, reset_order_state_manager
        reset_order_state_manager()
        osm = get_order_state_manager()

        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_state_manager=osm)
        GhostReconciliationMonitor().check(s, symbol=SYMBOL)

        osm_status = osm.status()
        assert "sync_count" in osm_status
        assert "ghost_detected_count" not in osm_status  # OrderStateManager's own vocabulary, unchanged


# ── Findings buffer ────────────────────────────────────────────────────

class TestFindingsBuffer:
    def test_finding_recorded_only_on_transition(self):
        mon = GhostReconciliationMonitor()
        s = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))

        mon.check(s, symbol=SYMBOL)
        mon.check(s, symbol=SYMBOL)
        mon.check(s, symbol=SYMBOL)

        findings = mon.get_recent_findings()
        assert len(findings) == 1
        assert findings[0]["status"] == DetectionStatus.ORPHAN_EXCHANGE.value

    def test_findings_most_recent_first(self):
        mon = GhostReconciliationMonitor()
        s = _sys(data_provider=_dp(True), journal_v2=_journal([], total_trades=0))
        mon.check(s, symbol=SYMBOL)

        s["data_provider"] = _dp(False)
        s["journal_v2"] = _journal([], total_trades=1)
        mon.check(s, symbol=SYMBOL)

        findings = mon.get_recent_findings()
        assert findings[0]["status"] == DetectionStatus.NO_POSITION.value
        assert findings[1]["status"] == DetectionStatus.ORPHAN_EXCHANGE.value


# ── Unknown / error handling ──────────────────────────────────────────

class TestUnknownAndErrors:
    def test_no_data_provider_is_unknown(self):
        s = _sys()
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.UNKNOWN.value

    def test_order_state_manager_failure_degrades_to_unknown_not_a_crash(self):
        bad_mgr = MagicMock()
        bad_mgr.get_order_state.side_effect = RuntimeError("boom")
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3),
                  order_state_manager=bad_mgr)
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL)
        assert result.status == DetectionStatus.UNKNOWN.value
        assert result.severity == "info"


# ── Serialization ──────────────────────────────────────────────────────

class TestSerialization:
    def test_to_dict_has_all_brief_required_fields(self):
        s = _sys(data_provider=_dp(False), journal_v2=_journal([], total_trades=3))
        result = GhostReconciliationMonitor().check(s, symbol=SYMBOL).to_dict()
        for field in (
            "symbol", "status", "severity", "exchange_state", "runtime_state",
            "journal_state", "timeline_state", "detected_at", "reason",
        ):
            assert field in result


# ── Singleton ────────────────────────────────────────────────────────

class TestSingleton:
    def test_get_and_reset_return_a_working_monitor(self):
        from system_health.ghost_reconciliation import (
            get_ghost_reconciliation_monitor,
            reset_ghost_reconciliation_monitor,
        )
        reset_ghost_reconciliation_monitor()
        mon1 = get_ghost_reconciliation_monitor()
        mon2 = get_ghost_reconciliation_monitor()
        assert mon1 is mon2
        reset_ghost_reconciliation_monitor()
        mon3 = get_ghost_reconciliation_monitor()
        assert mon3 is not mon1
