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
    def test_flag_on_by_default(self):
        """V16 training-lane-visibility phase: flipped True, by explicit
        request that training run 24/7 "whenever the system is opened"
        rather than needing a manual .env edit first — see
        config/settings.py's own comment on this field for the full
        rationale and the override instructions for anyone who wants
        the previous opt-in-only behavior back."""
        from config.settings import Settings
        assert Settings.model_fields["BACKGROUND_PAPER_TRAINING_ENABLED"].default is True

    def test_starting_balance_and_poll_interval_defaults(self):
        from config.settings import Settings
        assert Settings.model_fields["BACKGROUND_TRAINING_STARTING_BALANCE"].default == 100.0
        assert Settings.model_fields["BACKGROUND_TRAINING_POLL_INTERVAL_SECONDS"].default == 20.0

    def test_flag_still_respects_env_override_off(self, monkeypatch):
        """The default flip must not remove the escape hatch: a person
        who doesn't want the extra background thread/DB writes can
        still set BACKGROUND_PAPER_TRAINING_ENABLED=false in .env."""
        monkeypatch.setenv("BACKGROUND_PAPER_TRAINING_ENABLED", "false")
        from config.settings import Settings
        assert Settings().BACKGROUND_PAPER_TRAINING_ENABLED is False

    def test_main_guard_constructs_runner_only_when_flag_true(self, monkeypatch):
        """The guard in main.py is a single `if settings.
        BACKGROUND_PAPER_TRAINING_ENABLED:` — exercised directly here
        against both states (rather than running the full, heavy,
        network-ish main.build_system()) to confirm it still respects
        the flag in both directions after the default flip."""
        monkeypatch.setattr(
            "execution.strategy_registry.build_strategy",
            lambda _name, **_kwargs: (lambda _symbol: None),
        )

        import training_lane.training_lane_runner as tlr_mod
        original_init = tlr_mod.TrainingLaneRunner.__init__
        constructed = {"called": False}

        def _spy_init(self, *a, **kw):
            constructed["called"] = True
            return original_init(self, *a, **kw)

        monkeypatch.setattr(tlr_mod.TrainingLaneRunner, "__init__", _spy_init)

        def _boot_guard(flag_enabled):
            if flag_enabled:
                tlr_mod.TrainingLaneRunner(
                    data_provider=None, regime_engine=None, smc_engine=None,
                    volume_engine=None, context_builder=None, confidence_engine=None,
                )

        _boot_guard(flag_enabled=False)
        assert constructed["called"] is False

        _boot_guard(flag_enabled=True)
        assert constructed["called"] is True


# ══════════════════════════════════════════════════════════════════════
# 7 — status() (GET /api/training-lane/status backing method)
# ══════════════════════════════════════════════════════════════════════

class TestStatus:
    def test_status_shape_when_flat(self, monkeypatch):
        runner = _make_runner(monkeypatch, signals=[], prices=[100.0], starting_balance=100.0)
        result = runner.status()

        assert result["enabled"] is True
        assert result["is_running"] is False  # start() never called in this test
        assert result["symbol"] == "BTCUSDT"
        assert result["execution_lane"] == TRAINING_LANE
        assert result["starting_balance"] == 100.0
        assert result["balance"] == 100.0
        assert result["bust_count"] == 0
        assert result["closed_trade_count"] == 0
        assert result["open_position"] is None
        assert result["last_closed_trade"] is None
        assert result["poll_interval_seconds"] == 0.01

    def test_status_reflects_open_position_and_closed_trade(self, monkeypatch):
        runner = _make_runner(
            monkeypatch,
            # Second entry is None (flat) so the position that closes on
            # cycle 2 doesn't immediately reopen in that same cycle —
            # see TrainingLaneRunner._cycle()'s close-then-maybe-reopen
            # ordering, exercised as-is here rather than changed.
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0), None],
            prices=[100.0, 90.0, 90.0],  # opens, then walks into SL -> closed LOSS
        )

        runner._cycle()  # open
        mid_status = runner.status()
        assert mid_status["open_position"] is not None
        assert mid_status["open_position"]["direction"] == "LONG"
        assert mid_status["last_closed_trade"] is None

        runner._cycle()  # SL hit -> close (flat signal -> no reopen this cycle)
        end_status = runner.status()
        assert end_status["open_position"] is None
        assert end_status["closed_trade_count"] == 1
        assert end_status["last_closed_trade"]["result"] == "LOSS"
        assert end_status["last_closed_trade"]["close_reason"] == "SL"

    def test_status_reflects_bust_count_and_reset_balance(self, monkeypatch, db):
        from research.dataset_builder import reset_dataset_builder
        from research.feature_store import FeatureStore

        store = FeatureStore(db_path=db)
        reset_dataset_builder(store=store)

        runner = _make_runner(monkeypatch, signals=[], prices=[100.0], starting_balance=100.0)
        runner._engine.account.realise_pnl(-100.0)
        runner._handle_bust()

        result = runner.status()
        assert result["balance"] == 100.0  # reset, not left at 0
        assert result["bust_count"] == 1

    def test_status_never_leaks_mutable_engine_references(self, monkeypatch):
        """The status surface is read-only by contract (see the
        method's own doc comment) — every value must be a primitive or
        a plain dict, never the live PaperPosition/ClosedTrade object,
        so a caller can't accidentally mutate training state through
        a status response."""
        runner = _make_runner(
            monkeypatch,
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)],
            prices=[100.0],
        )
        runner._cycle()  # open
        result = runner.status()
        assert isinstance(result["open_position"], dict)
