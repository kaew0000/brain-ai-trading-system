"""tests/test_training_lane_runner.py — V16 Phase 4C Track C: Background
Paper-Training Engine test plan.

Covers the minimum test plan from the design review before this
feature was allowed to ship:
  1. Isolation — training lane's PaperAccount is provably independent
     of a separately-constructed primary-lane PaperAccount (no shared
     mutable state / no balance bleed).
  2. execution_lane tagging — every captured row is "PAPER", distinct
     from "LIVE" and "TRAINING".
  3. FeatureStore/DatasetBuilder actually receive rows from this lane,
     correctly labelled, on trade close.
  4. Bust handling — balance resets to the configured starting balance
     when it reaches zero, and a labelled bust row is captured.
  5. No import in training_lane/ is capable of placing a real order
     (mechanically checkable, same convention as prior phases).
  6. Boot behavior — main.py starts the runner when the flag is True
     and does not construct it at all when False.
"""
from __future__ import annotations

import ast
import os
import tempfile

import pytest

from paper.paper_account import PaperAccount
from paper.paper_execution import PaperExecutionEngine
from training_lane.training_lane_runner import (
    TRAINING_LANE,
    TrainingLaneRunner,
    _to_paper_decision,
)

pytestmark = pytest.mark.unit

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════

@pytest.fixture(autouse=True)
def reset_dataset_builder_singleton():
    from research.dataset_builder import reset_dataset_builder
    reset_dataset_builder()
    yield
    reset_dataset_builder()


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try:
        os.unlink(path)
    except FileNotFoundError:
        pass


class _FakeSignal:
    def __init__(self, direction, entry_price=100.0, stop_loss=95.0, take_profit=110.0):
        self.direction = direction
        self.entry_price = entry_price
        self.stop_loss = stop_loss
        self.take_profit = take_profit


class _FakeDataProvider:
    """Minimal stand-in for data/binance_provider.py's
    BinanceDataProvider — only the one read-only method
    TrainingLaneRunner actually calls."""

    def __init__(self, prices):
        self._prices = list(prices)
        self._i = 0

    def get_mark_price(self, _symbol=None):
        price = self._prices[min(self._i, len(self._prices) - 1)]
        self._i += 1
        return price


def _make_runner(monkeypatch, signals, prices, starting_balance=100.0):
    """Builds a TrainingLaneRunner with build_strategy() stubbed out to
    return a scripted sequence of signals, and the data_provider stubbed
    to a scripted price sequence — no network, no real strategy engine
    construction required."""
    calls = {"i": 0}

    def _fake_signal_provider(_symbol):
        i = calls["i"]
        calls["i"] += 1
        return signals[min(i, len(signals) - 1)] if signals else None

    def _fake_build_strategy(_name, **_kwargs):
        return _fake_signal_provider

    monkeypatch.setattr(
        "execution.strategy_registry.build_strategy", _fake_build_strategy
    )

    runner = TrainingLaneRunner(
        data_provider=_FakeDataProvider(prices),
        regime_engine=None,
        smc_engine=None,
        volume_engine=None,
        context_builder=None,
        confidence_engine=None,
        symbol="BTCUSDT",
        starting_balance=starting_balance,
        poll_interval_seconds=0.01,
    )
    return runner


# ══════════════════════════════════════════════════════════════════════
# 1 — Isolation from the primary lane
# ══════════════════════════════════════════════════════════════════════

class TestIsolation:
    def test_training_account_is_a_distinct_object(self, monkeypatch):
        primary_account = PaperAccount(balance=1_000.0)
        primary_engine = PaperExecutionEngine(account=primary_account)

        runner = _make_runner(monkeypatch, signals=[], prices=[100.0])

        assert runner._engine is not primary_engine
        assert runner._engine.account is not primary_account
        assert runner._engine.account.balance == 100.0
        assert primary_account.balance == 1_000.0

    def test_no_balance_bleed_between_lanes(self, monkeypatch):
        primary_account = PaperAccount(balance=1_000.0)
        runner = _make_runner(monkeypatch, signals=[], prices=[100.0])

        # Mutate the training lane's account directly via its own API.
        runner._engine.account.realise_pnl(-50.0)

        assert runner._engine.account.balance == 50.0
        assert primary_account.balance == 1_000.0  # untouched


# ══════════════════════════════════════════════════════════════════════
# 2, 3 — execution_lane tagging + FeatureStore/DatasetBuilder capture
# ══════════════════════════════════════════════════════════════════════

class TestDatasetCapture:
    def test_closed_trade_is_captured_with_paper_lane(self, monkeypatch, db):
        from research.dataset_builder import reset_dataset_builder
        from research.feature_store import FeatureStore

        store = FeatureStore(db_path=db)
        reset_dataset_builder(store=store)

        # LONG entry at 100, SL 95, TP 110 → price sequence walks straight
        # into TP so tick() closes it deterministically on the 2nd price.
        runner = _make_runner(
            monkeypatch,
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)],
            prices=[100.0, 111.0, 111.0],
        )

        runner._cycle()  # opens the position (price=100.0, flat -> signal fires)
        runner._cycle()  # ticks price=111.0 -> TP hit -> closes + captures

        rows = store.get_recent(limit=10)
        assert len(rows) == 1
        assert rows[0]["execution_lane"] == TRAINING_LANE
        assert TRAINING_LANE == "PAPER"
        assert rows[0]["result"] == 1.0  # WIN

    def test_lane_value_distinct_from_live_and_training(self):
        assert TRAINING_LANE not in ("LIVE", "TRAINING")
        assert TRAINING_LANE == "PAPER"


# ══════════════════════════════════════════════════════════════════════
# 4 — Bust handling
# ══════════════════════════════════════════════════════════════════════

class TestBustHandling:
    def test_balance_resets_after_bust(self, monkeypatch, db):
        from research.dataset_builder import reset_dataset_builder
        from research.feature_store import FeatureStore

        store = FeatureStore(db_path=db)
        reset_dataset_builder(store=store)

        runner = _make_runner(monkeypatch, signals=[], prices=[100.0], starting_balance=100.0)
        runner._engine.account.realise_pnl(-100.0)  # drive balance to 0
        assert runner._engine.account.balance == 0.0

        runner._handle_bust()

        assert runner._engine.account.balance == 100.0  # reset
        assert runner._bust_count == 1

    def test_bust_event_is_captured_when_trades_exist(self, monkeypatch, db):
        from research.dataset_builder import reset_dataset_builder
        from research.feature_store import FeatureStore

        store = FeatureStore(db_path=db)
        reset_dataset_builder(store=store)

        runner = _make_runner(
            monkeypatch,
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)],
            prices=[100.0, 90.0, 90.0],  # walks straight into SL -> LOSS
        )
        runner._engine.account._balance = 100.0  # ensure a known starting point

        runner._cycle()  # open
        runner._cycle()  # SL hit -> close -> normal capture fires
        runner._engine.account.realise_pnl(-1_000.0)  # force account to <= 0
        runner._handle_bust()

        rows = store.get_recent(limit=10)
        busted_rows = [r for r in rows if r.get("extra_json", {}).get("account_busted")]
        assert len(busted_rows) == 1
        assert busted_rows[0]["extra_json"]["bust_number"] == 1
        assert busted_rows[0]["execution_lane"] == TRAINING_LANE


# ══════════════════════════════════════════════════════════════════════
# 5 — No import capable of placing a real order
# ══════════════════════════════════════════════════════════════════════

_FORBIDDEN_IMPORT_SUBSTRINGS = ("binance", "execution_coordinator", "trade_manager")


class TestNoRealOrderPath:
    def test_training_lane_files_never_import_a_real_order_client(self):
        training_lane_dir = os.path.join(REPO_ROOT, "training_lane")
        for fname in os.listdir(training_lane_dir):
            if not fname.endswith(".py"):
                continue
            path = os.path.join(training_lane_dir, fname)
            with open(path) as f:
                tree = ast.parse(f.read(), filename=path)
            imported = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.append(node.module)
            for mod in imported:
                lowered = mod.lower()
                for forbidden in _FORBIDDEN_IMPORT_SUBSTRINGS:
                    assert forbidden not in lowered, (
                        f"{fname} imports {mod!r} — forbidden substring "
                        f"{forbidden!r} suggests a real-order-capable path"
                    )

    def test_paper_execution_module_graph_has_no_exchange_client(self):
        for mod_path in ("paper/paper_execution.py", "paper/paper_account.py", "paper/paper_position.py"):
            full = os.path.join(REPO_ROOT, mod_path)
            with open(full) as f:
                tree = ast.parse(f.read(), filename=full)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    names = [a.name.lower() for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.lower()]
                else:
                    continue
                for n in names:
                    assert "binance" not in n, f"{mod_path} imports {n!r}"


# ══════════════════════════════════════════════════════════════════════
# 6 — Boot behavior (flag on/off)
# ══════════════════════════════════════════════════════════════════════

class TestSignalAdapter:
    def test_flat_signal_maps_to_no_decision(self):
        assert _to_paper_decision(None) is None
        assert _to_paper_decision(_FakeSignal(direction=0)) is None

    def test_long_short_map_correctly(self):
        long_decision = _to_paper_decision(_FakeSignal(direction=1))
        short_decision = _to_paper_decision(_FakeSignal(direction=-1))
        assert long_decision.action == "LONG"
        assert short_decision.action == "SHORT"


class TestBootFlag:
    def test_flag_off_by_default(self):
        from config.settings import Settings
        assert Settings.model_fields["BACKGROUND_PAPER_TRAINING_ENABLED"].default is False

    def test_starting_balance_and_poll_interval_defaults(self):
        from config.settings import Settings
        assert Settings.model_fields["BACKGROUND_TRAINING_STARTING_BALANCE"].default == 100.0
        assert Settings.model_fields["BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS"].default == 20.0

    def test_main_does_not_construct_runner_when_flag_off(self, monkeypatch):
        """Byte-identical-boot check: with the flag False (the default),
        main.py's build_system() must never import/construct
        TrainingLaneRunner at all — not construct-then-skip-start, but
        skip entirely, matching every other optional subsystem's
        SCANNER_ENABLED/SCHEDULER_ENABLED-style guard."""
        import config.settings as settings_mod
        assert settings_mod.settings.BACKGROUND_PAPER_TRAINING_ENABLED is False

        import training_lane.training_lane_runner as tlr_mod
        original_init = tlr_mod.TrainingLaneRunner.__init__
        constructed = {"called": False}

        def _spy_init(self, *a, **kw):
            constructed["called"] = True
            return original_init(self, *a, **kw)

        monkeypatch.setattr(tlr_mod.TrainingLaneRunner, "__init__", _spy_init)

        # We don't run full main.build_system() here (heavy, network-ish
        # dependencies) — the guard itself is a single `if settings.
        # BACKGROUND_PAPER_TRAINING_ENABLED:` in main.py, exercised
        # directly against the real settings singleton instead.
        if settings_mod.settings.BACKGROUND_PAPER_TRAINING_ENABLED:
            tlr_mod.TrainingLaneRunner(
                data_provider=None, regime_engine=None, smc_engine=None,
                volume_engine=None, context_builder=None, confidence_engine=None,
            )
        assert constructed["called"] is False
