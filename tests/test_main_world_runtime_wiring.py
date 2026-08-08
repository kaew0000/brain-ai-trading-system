"""tests/test_main_world_runtime_wiring.py — Phase W13-1

Covers exactly the two functions W13-1 touched in main.py:
_get_world_runtime_manager() (reader wiring) and
_run_world_runtime_manager() (export_snapshot call). Does not import or
exercise the trading loop itself — main.py's module-level code has no
side effects at import time (guarded by `if __name__ == "__main__"`),
confirmed before writing this file.
"""
from __future__ import annotations

import pytest

import main as _main
from world.readers.order_reader import OrderReader

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _reset_cached_manager():
    """_world_runtime_manager is a module-level lazy singleton — reset
    it before and after every test so tests never leak the cached
    instance into each other."""
    _main._world_runtime_manager = None
    yield
    _main._world_runtime_manager = None


def test_get_world_runtime_manager_wires_order_reader():
    manager = _main._get_world_runtime_manager()
    order_reader = manager._adapter._readers["orders"]
    assert isinstance(order_reader, OrderReader)


def test_get_world_runtime_manager_is_cached_singleton():
    first = _main._get_world_runtime_manager()
    second = _main._get_world_runtime_manager()
    assert first is second


def test_run_world_runtime_manager_passes_order_timeline_and_reconciliation_engine(monkeypatch):
    captured = {}

    def _fake_export_snapshot(*, journal=None, order_timeline=None, reconciliation_engine=None, **kwargs):
        captured["journal"] = journal
        captured["order_timeline"] = order_timeline
        captured["reconciliation_engine"] = reconciliation_engine
        return kwargs.get("staging_dir", "")

    import telemetry.world_export as we
    monkeypatch.setattr(we, "export_snapshot", _fake_export_snapshot)

    class _StubManager:
        def run_once(self):
            pass

    monkeypatch.setattr(_main, "_get_world_runtime_manager", lambda: _StubManager())

    sentinel_ot = object()
    sentinel_rc = object()
    _main._run_world_runtime_manager({
        "journal_v2": "j", "order_timeline": sentinel_ot, "reconciliation_engine": sentinel_rc,
    })

    assert captured["journal"] == "j"
    assert captured["order_timeline"] is sentinel_ot
    assert captured["reconciliation_engine"] is sentinel_rc


def test_run_world_runtime_manager_tolerates_missing_components(monkeypatch):
    """components dict without "order_timeline"/"reconciliation_engine"
    keys (e.g. an older call site, or a deployment without them wired)
    must not raise — same "a World failure must never affect the
    trading loop" contract this function already documents. Stubs
    export_snapshot() itself (rather than DEFAULT_STAGING_DIR, which
    export_snapshot()'s own default parameter value already captured
    at import time) so this test never writes into the repo's real
    world/data/runtime_input/ staging directory as a side effect —
    real writes with real tmp_path redirection are already covered by
    tests/test_world_export.py."""
    import telemetry.world_export as we
    monkeypatch.setattr(we, "export_snapshot", lambda **kwargs: "")

    class _StubManager:
        def run_once(self):
            pass

    monkeypatch.setattr(_main, "_get_world_runtime_manager", lambda: _StubManager())
    _main._run_world_runtime_manager({})  # must not raise


def test_run_world_runtime_manager_swallows_export_snapshot_failure(monkeypatch):
    import telemetry.world_export as we
    monkeypatch.setattr(
        we, "export_snapshot",
        lambda **kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    _main._run_world_runtime_manager({})  # must not raise
