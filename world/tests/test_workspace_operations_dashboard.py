"""Phase W12: operations_dashboard — top-strip summary."""
from world.runtime.models import TelemetryState, WorldState
from world.workspace.operations_dashboard import build_operations_summary


def test_idle_engine_status_is_not_emergency():
    state = WorldState(engine_status="idle")
    summary = build_operations_summary(state)
    assert summary.mode == "unknown"


def test_halted_engine_status_is_emergency():
    state = WorldState(engine_status="halted")
    summary = build_operations_summary(state)
    assert summary.mode == "emergency"


def test_recovering_engine_status_is_emergency():
    state = WorldState(engine_status="recovering")
    summary = build_operations_summary(state)
    assert summary.mode == "emergency"


def test_account_equity_is_none_no_verified_accessor():
    """Documented gap — see operations_dashboard.py's module docstring."""
    state = WorldState()
    summary = build_operations_summary(state)
    assert summary.account_equity is None


def test_active_mission_count_reflects_real_missions():
    from world.runtime.models import MissionState
    missions = (
        MissionState(mission_id="m1", title="X", district="ceo-tower", status="active"),
        MissionState(mission_id="m2", title="Y", district="ceo-tower", status="complete"),
    )
    state = WorldState(missions=missions)
    summary = build_operations_summary(state)
    assert summary.active_mission_count == 1


def test_cpu_and_ram_pulled_from_telemetry():
    telemetry = (
        TelemetryState(name="system.cpu_percent", value=42.0),
        TelemetryState(name="system.ram_percent", value=55.0),
    )
    state = WorldState(telemetry=telemetry)
    summary = build_operations_summary(state)
    assert summary.cpu_percent == 42.0
    assert summary.ram_percent == 55.0


def test_exchange_connected_true_when_any_heartbeat_present():
    telemetry = (TelemetryState(name="heartbeat.websocket.age_s", value=1.2),)
    state = WorldState(telemetry=telemetry)
    summary = build_operations_summary(state)
    assert summary.exchange_connected is True


def test_exchange_connected_false_with_no_heartbeats():
    state = WorldState()
    summary = build_operations_summary(state)
    assert summary.exchange_connected is False


def test_drawdown_from_portfolio_summary_when_present():
    from world.runtime.models import PortfolioSummaryState
    state = WorldState(portfolio_summary=PortfolioSummaryState(drawdown=0.12))
    summary = build_operations_summary(state)
    assert summary.drawdown == 0.12


def test_serializes_to_dict():
    import json
    state = WorldState()
    json.dumps(build_operations_summary(state).to_dict())


# ── W13-1/W13-4 additive orders/reconciliation fields ────────────────────

def test_active_orders_count_zero_by_default():
    state = WorldState()
    summary = build_operations_summary(state)
    assert summary.active_orders_count == 0
    assert summary.reconciliation_last_result is None
    assert summary.reconciliation_event_count is None


def test_active_orders_count_reflects_real_orders():
    from world.runtime.models import OrderTimelineState
    orders = (
        OrderTimelineState(symbol="BTCUSDT", state="OPEN"),
        OrderTimelineState(symbol="ETHUSDT", state="CLOSING"),
    )
    state = WorldState(orders=orders)
    summary = build_operations_summary(state)
    assert summary.active_orders_count == 2


def test_reconciliation_fields_reflect_real_reconciliation_state():
    from world.runtime.models import ReconciliationState
    state = WorldState(reconciliation=ReconciliationState(last_result="clean", event_count=4))
    summary = build_operations_summary(state)
    assert summary.reconciliation_last_result == "clean"
    assert summary.reconciliation_event_count == 4


def test_to_dict_includes_orders_and_reconciliation_keys():
    state = WorldState()
    data = build_operations_summary(state).to_dict()
    assert data["activeOrdersCount"] == 0
    assert data["reconciliationLastResult"] is None
    assert data["reconciliationEventCount"] is None
