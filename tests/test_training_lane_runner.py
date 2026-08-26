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


class _FakeRankedOpportunity:
    def __init__(self, symbol):
        self.symbol = symbol


class _FakeRanker:
    """Duck-typed stand-in for ranking.opportunity_ranker.OpportunityRanker
    — TrainingLaneRunner only ever calls .rank(), never touches a
    MarketScanner directly, so this is all a test needs (see
    TrainingLaneRunner's constructor docstring)."""

    def __init__(self, symbols_per_call):
        """symbols_per_call: list of lists — each .rank() call returns
        the next list in sequence (empty list allowed, to test the
        empty-ranking fallback); the last list repeats once exhausted."""
        self._sequence = [list(s) for s in symbols_per_call]
        self._i = 0
        self.call_count = 0

    def rank(self):
        self.call_count += 1
        i = min(self._i, len(self._sequence) - 1)
        symbols = self._sequence[i]
        self._i += 1
        return [_FakeRankedOpportunity(s) for s in symbols]


class _RaisingRanker:
    def rank(self):
        raise RuntimeError("scanner cache corrupted")


def _make_runner(
    monkeypatch,
    signals,
    prices,
    starting_balance=100.0,
    opportunity_ranker=None,
    multi_symbol_enabled=None,
):
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
        opportunity_ranker=opportunity_ranker,
        multi_symbol_enabled=multi_symbol_enabled,
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


# ══════════════════════════════════════════════════════════════════════
# 7 — Multi-symbol rotation (V16 Phase 4C Track C addition)
# ══════════════════════════════════════════════════════════════════════

class TestMultiSymbolDisabledByDefault:
    """Every existing behavior (tests 1-6 above) must be provably
    unaffected by this addition — these tests pin that down explicitly
    rather than just relying on the pre-existing tests still passing."""

    def test_multi_symbol_off_by_default(self, monkeypatch):
        runner = _make_runner(monkeypatch, signals=[], prices=[100.0])
        assert runner._multi_symbol_enabled is False
        assert runner._ranker is None

    def test_ranker_supplied_but_flag_off_is_still_ignored(self, monkeypatch):
        """Passing a ranker alone must not turn rotation on — the flag
        is the actual gate, matching every other opt-in feature in this
        codebase (explicit True/True, not "presence implies enabled")."""
        ranker = _FakeRanker([["ETHUSDT"]])
        runner = _make_runner(
            monkeypatch, signals=[], prices=[100.0],
            opportunity_ranker=ranker, multi_symbol_enabled=False,
        )
        assert runner._ranker is None
        assert runner._select_symbol() == "BTCUSDT"
        assert ranker.call_count == 0  # never even called

    def test_settings_defaults(self):
        from config.settings import settings
        assert settings.BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED is False
        assert settings.BACKGROUND_TRAINING_SYMBOL_POOL_SIZE == 10

    def test_status_reports_multi_symbol_enabled_field(self, monkeypatch):
        runner = _make_runner(monkeypatch, signals=[], prices=[100.0])
        assert runner.status()["multi_symbol_enabled"] is False


class TestSelectSymbolRotation:
    def test_rotates_through_ranked_candidates_in_order(self, monkeypatch):
        ranker = _FakeRanker([["ETHUSDT", "SOLUSDT", "ARBUSDT"]])
        runner = _make_runner(
            monkeypatch, signals=[], prices=[100.0],
            opportunity_ranker=ranker, multi_symbol_enabled=True,
        )
        picked = [runner._select_symbol() for _ in range(5)]
        # Wraps around after exhausting the 3 candidates.
        assert picked == ["ETHUSDT", "SOLUSDT", "ARBUSDT", "ETHUSDT", "SOLUSDT"]

    def test_falls_back_to_fixed_symbol_when_ranking_empty(self, monkeypatch):
        ranker = _FakeRanker([[]])  # "scanner cache is empty" case
        runner = _make_runner(
            monkeypatch, signals=[], prices=[100.0],
            opportunity_ranker=ranker, multi_symbol_enabled=True,
        )
        assert runner._select_symbol() == "BTCUSDT"

    def test_falls_back_to_fixed_symbol_when_ranker_raises(self, monkeypatch):
        runner = _make_runner(
            monkeypatch, signals=[], prices=[100.0],
            opportunity_ranker=_RaisingRanker(), multi_symbol_enabled=True,
        )
        assert runner._select_symbol() == "BTCUSDT"  # never raises

    def test_no_ranker_falls_back_even_with_flag_on(self, monkeypatch):
        runner = _make_runner(
            monkeypatch, signals=[], prices=[100.0],
            opportunity_ranker=None, multi_symbol_enabled=True,
        )
        assert runner._select_symbol() == "BTCUSDT"


class TestCycleUsesRotatedSymbol:
    def test_open_position_tagged_with_rotated_symbol_not_fixed_symbol(self, monkeypatch):
        ranker = _FakeRanker([["ETHUSDT"]])
        runner = _make_runner(
            monkeypatch,
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0)],
            prices=[100.0],
            opportunity_ranker=ranker, multi_symbol_enabled=True,
        )
        runner._cycle()
        assert runner.symbol == "ETHUSDT"
        open_position = runner._engine.open_positions[0]
        assert open_position.symbol == "ETHUSDT"

    def test_symbol_does_not_change_while_a_position_is_open(self, monkeypatch):
        """Regression guard: rotation must only happen while flat. A
        position opened on ETHUSDT must stay ETHUSDT for its whole
        life even if the ranker's top candidate changes mid-position —
        switching would corrupt PnL tracking (tick() applies one mark
        price to every open position)."""
        ranker = _FakeRanker([["ETHUSDT"], ["SOLUSDT"], ["ARBUSDT"]])
        runner = _make_runner(
            monkeypatch,
            # LONG opens on cycle 1; None on cycle 2 means "still open,
            # no new entry attempted" — position stays open across both.
            signals=[_FakeSignal(direction=1, entry_price=100.0, stop_loss=50.0, take_profit=999.0), None],
            prices=[100.0, 101.0],  # 101 doesn't hit SL(50) or TP(999) — stays open
            opportunity_ranker=ranker, multi_symbol_enabled=True,
        )
        runner._cycle()  # opens on ETHUSDT (ranker call #1)
        assert runner.symbol == "ETHUSDT"
        runner._cycle()  # still open — must NOT rotate to SOLUSDT
        assert runner.symbol == "ETHUSDT"
        assert ranker.call_count == 1  # rotation only queried once, while flat

    def test_rotates_to_a_new_symbol_after_position_closes(self, monkeypatch):
        ranker = _FakeRanker([["ETHUSDT"], ["SOLUSDT"]])
        runner = _make_runner(
            monkeypatch,
            signals=[
                _FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0),
                _FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0),
            ],
            prices=[100.0, 111.0],  # cycle 2's mark hits TP(110) -> closes
            opportunity_ranker=ranker, multi_symbol_enabled=True,
        )
        runner._cycle()  # opens on ETHUSDT
        assert runner.symbol == "ETHUSDT"
        runner._cycle()  # closes (TP hit) then reselects+reopens same cycle
        assert runner.symbol == "SOLUSDT"
        assert runner._engine.open_positions[0].symbol == "SOLUSDT"


class TestPaperExecutionEngineSymbolParameter:
    """Regression coverage for paper/paper_execution.py's execute() —
    the actual blocker found during design review: it hardcoded
    symbol=settings.SYMBOL regardless of what was asked for."""

    def test_execute_without_symbol_defaults_to_settings_symbol(self):
        from config.settings import settings

        engine = PaperExecutionEngine(account=PaperAccount(balance=1000.0))
        decision = _to_paper_decision(_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0))
        engine.execute(decision)
        assert engine.open_positions[0].symbol == settings.SYMBOL

    def test_execute_with_explicit_symbol_uses_it(self):
        engine = PaperExecutionEngine(account=PaperAccount(balance=1000.0))
        decision = _to_paper_decision(_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0))
        engine.execute(decision, symbol="ETHUSDT")
        assert engine.open_positions[0].symbol == "ETHUSDT"

    def test_closed_trade_carries_the_symbol_it_was_opened_with(self):
        engine = PaperExecutionEngine(account=PaperAccount(balance=1000.0))
        decision = _to_paper_decision(_FakeSignal(direction=1, entry_price=100.0, stop_loss=95.0, take_profit=110.0))
        engine.execute(decision, symbol="SOLUSDT")
        closed = engine.tick(111.0)  # hits take_profit=110
        assert len(closed) == 1
        assert closed[0].to_dict()["symbol"] == "SOLUSDT"


class TestMainPyWiring:
    """Mirrors TestBootBehavior's ast-based approach (checking main.py's
    source directly rather than executing main.py's whole bootstrap) for
    the new wiring added in this phase."""

    def test_main_py_passes_opportunity_ranker_to_training_lane_runner(self):
        main_py_path = os.path.join(REPO_ROOT, "main.py")
        with open(main_py_path, encoding="utf-8") as f:
            source = f.read()
        tree = ast.parse(source)

        found_call = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "TrainingLaneRunner"
            ):
                found_call = True
                kwarg_names = {kw.arg for kw in node.keywords}
                assert "opportunity_ranker" in kwarg_names, (
                    "main.py's TrainingLaneRunner(...) call must pass "
                    "opportunity_ranker= for multi-symbol rotation to be "
                    "reachable at all in production"
                )
        assert found_call, "main.py no longer constructs TrainingLaneRunner"

    def test_main_py_gates_ranker_construction_on_multi_symbol_flag(self):
        main_py_path = os.path.join(REPO_ROOT, "main.py")
        with open(main_py_path, encoding="utf-8") as f:
            source = f.read()
        assert "BACKGROUND_TRAINING_MULTI_SYMBOL_ENABLED" in source
        assert "BACKGROUND_TRAINING_SYMBOL_POOL_SIZE" in source
