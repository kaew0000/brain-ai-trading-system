"""
tests/test_phase3_complete.py
==============================
Phase 3A + 3B + 3C — complete test coverage.
No mocks-only: all critical paths call real functions from main.py.
"""
from __future__ import annotations
import os, tempfile, pytest
from unittest.mock import MagicMock
import numpy as np
import pandas as pd

pytestmark = pytest.mark.unit


# ── autouse fixtures ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_all():
    from system_health.heartbeat import reset_heartbeat
    from system_health.watchdog import reset_watchdog
    from system_health.reconciliation import reset_reconciliation_engine
    from system_health.recovery_engine import reset_recovery_engine
    from ml.meta_label import reset_meta_label_filter
    from ml.ml_advisor import reset_ml_advisor
    from research.dataset_builder import reset_dataset_builder
    from missions.mission_tracker import reset_mission_tracker
    from events.event_bus import reset_event_bus
    reset_heartbeat(); reset_watchdog(); reset_reconciliation_engine()
    reset_recovery_engine(); reset_meta_label_filter(); reset_ml_advisor()
    reset_dataset_builder(); reset_mission_tracker()
    reset_event_bus(journal=None, persist=False)
    yield
    reset_heartbeat(); reset_watchdog(); reset_reconciliation_engine()
    reset_recovery_engine(); reset_meta_label_filter(); reset_ml_advisor()
    reset_dataset_builder(); reset_mission_tracker()
    reset_event_bus(journal=None, persist=False)


@pytest.fixture
def db():
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        path = f.name
    yield path
    try: os.unlink(path)
    except FileNotFoundError: pass


# ════════════════════════════════════════════════════════════════════════════
# 3A — Heartbeat
# ════════════════════════════════════════════════════════════════════════════

class TestHeartbeat:
    def test_beat_and_get(self):
        from system_health.heartbeat import get_heartbeat
        hb = get_heartbeat()
        hb.beat("main_loop")
        assert hb.get("main_loop") is not None

    def test_unknown_returns_none(self):
        from system_health.heartbeat import get_heartbeat
        assert get_heartbeat().get("nonexistent") is None

    def test_beat_with_meta(self):
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("trade_manager", meta={"ok": True})
        assert get_heartbeat().get("trade_manager")["meta"]["ok"] is True

    def test_never_raises(self):
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("x", meta={"obj": object()})  # non-serialisable

    def test_clear(self):
        from system_health.heartbeat import get_heartbeat
        hb = get_heartbeat()
        hb.beat("a"); hb.clear()
        assert hb.get_all() == {}

    def test_singleton(self):
        from system_health.heartbeat import get_heartbeat, reset_heartbeat
        a = get_heartbeat(); b = reset_heartbeat()
        assert a is not b
        assert get_heartbeat() is b

    def test_thread_safety(self):
        import threading
        from system_health.heartbeat import get_heartbeat
        errs = []
        def go():
            try:
                for i in range(30): get_heartbeat().beat(f"s{i%3}")
            except Exception as e: errs.append(e)
        ts = [threading.Thread(target=go) for _ in range(5)]
        for t in ts: t.start()
        for t in ts: t.join()
        assert errs == []


# ════════════════════════════════════════════════════════════════════════════
# 3A — Watchdog
# ════════════════════════════════════════════════════════════════════════════

class TestWatchdog:
    def test_snapshot_has_required_keys(self):
        from system_health.watchdog import get_watchdog
        s = get_watchdog().snapshot()
        assert {"subsystems","overall_status","timestamp"} <= s.keys()

    def test_unbeaten_is_dead(self):
        from system_health.watchdog import get_watchdog
        s = get_watchdog().snapshot()
        assert s["subsystems"]["main_loop"]["status"] == "DEAD"

    def test_overall_critical_when_any_dead(self):
        from system_health.watchdog import get_watchdog
        assert get_watchdog().snapshot()["overall_status"] == "CRITICAL"

    def test_fresh_beat_is_alive(self):
        from system_health.heartbeat import get_heartbeat
        from system_health.watchdog import get_watchdog
        get_heartbeat().beat("main_loop")
        s = get_watchdog().snapshot()
        assert s["subsystems"]["main_loop"]["status"] == "ALIVE"

    def test_all_beaten_is_healthy(self):
        from system_health.heartbeat import get_heartbeat
        from system_health.watchdog import get_watchdog, DEFAULT_SUBSYSTEMS
        for n in DEFAULT_SUBSYSTEMS: get_heartbeat().beat(n)
        assert get_watchdog().is_healthy() is True

    def test_classify_stale(self):
        from system_health.watchdog import Watchdog
        wd = Watchdog()
        assert wd._classify(3.0, 1.0) == "STALE"

    def test_classify_dead(self):
        from system_health.watchdog import Watchdog
        wd = Watchdog()
        assert wd._classify(10.0, 1.0) == "DEAD"

    def test_classify_none_dead(self):
        from system_health.watchdog import Watchdog
        assert Watchdog()._classify(None, 10.0) == "DEAD"

    def test_snapshot_never_raises_on_hb_failure(self, monkeypatch):
        import system_health.heartbeat as hb
        monkeypatch.setattr(hb, "get_heartbeat", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
        from system_health.watchdog import get_watchdog
        s = get_watchdog().snapshot()
        assert s["overall_status"] == "CRITICAL"

    def test_singleton(self):
        from system_health.watchdog import get_watchdog, reset_watchdog
        a = get_watchdog(); b = reset_watchdog()
        assert a is not b


# ════════════════════════════════════════════════════════════════════════════
# 3A — ReconciliationEngine
# ════════════════════════════════════════════════════════════════════════════

def _sys(ex_pos=None, j_open=None, paper=None):
    dp = MagicMock(); dp.get_position_info.return_value = ex_pos
    jrn = MagicMock(); jrn.get_open_trades.return_value = j_open or []
    d = {"data_provider": dp, "journal_v2": jrn, "paper_engine": None}
    if paper is not None:
        pe = MagicMock(); pe.get_open_positions.return_value = paper
        d["paper_engine"] = pe
    return d

class TestReconciliation:
    def test_all_flat_no_event(self):
        from system_health.reconciliation import get_reconciliation_engine
        assert get_reconciliation_engine().run(_sys()) is None

    def test_presence_mismatch_detected(self):
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol":"BTC","positionAmt":0.1,"entryPrice":67000.0,"unrealizedProfit":5.0,"side":"LONG"}
        evt = get_reconciliation_engine().run(_sys(ex_pos=exch))
        assert evt is not None
        assert evt.mismatch_type == "PRESENCE_MISMATCH"

    def test_side_mismatch(self):
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol":"BTC","positionAmt":0.1,"entryPrice":67000.0,"unrealizedProfit":5.0,"side":"LONG"}
        journal = [{"id":1,"direction":"SHORT","quantity":0.1}]
        evt = get_reconciliation_engine().run(_sys(ex_pos=exch, j_open=journal))
        assert evt.mismatch_type == "SIDE_MISMATCH"

    def test_duplicate_journal_trades(self):
        from system_health.reconciliation import get_reconciliation_engine
        journal = [{"id":1,"direction":"LONG","quantity":0.1},
                   {"id":2,"direction":"LONG","quantity":0.1}]
        evt = get_reconciliation_engine().run(_sys(j_open=journal))
        assert evt.mismatch_type == "DUPLICATE_JOURNAL_TRADES"

    def test_ghost_row_auto_closed(self):
        from system_health.reconciliation import get_reconciliation_engine
        jrn = MagicMock()
        jrn.get_open_trades.return_value = [{"id":42,"direction":"LONG","quantity":0.1}]
        jrn.update_trade_result = MagicMock(return_value=True)
        dp = MagicMock(); dp.get_position_info.return_value = None
        sys_d = {"data_provider": dp, "journal_v2": jrn, "paper_engine": None}
        evt = get_reconciliation_engine().run(sys_d)
        assert evt.recovery_result == "closed_ghost_journal_row"
        jrn.update_trade_result.assert_called_once_with(42, "CANCELLED", 0.0, 0.0)

    def test_never_calls_execute_trade(self):
        from system_health.reconciliation import get_reconciliation_engine
        exch = {"symbol":"BTC","positionAmt":0.1,"entryPrice":67000.0,"unrealizedProfit":5.0,"side":"LONG"}
        journal = [{"id":1,"direction":"SHORT","quantity":0.5}]
        tm = MagicMock()
        sys_d = _sys(ex_pos=exch, j_open=journal)
        sys_d["trade_manager"] = tm
        get_reconciliation_engine().run(sys_d)
        tm.execute_trade.assert_not_called()

    def test_api_error_not_false_mismatch(self):
        from system_health.reconciliation import get_reconciliation_engine
        dp = MagicMock(); dp.get_position_info.side_effect = RuntimeError("timeout")
        jrn = MagicMock(); jrn.get_open_trades.return_value = []
        assert get_reconciliation_engine().run({"data_provider":dp,"journal_v2":jrn,"paper_engine":None}) is None

    def test_run_never_raises(self):
        from system_health.reconciliation import get_reconciliation_engine
        assert get_reconciliation_engine().run({}) is None

    def test_publishes_to_event_bus(self):
        from system_health.reconciliation import get_reconciliation_engine
        from events.event_bus import get_event_bus
        exch = {"symbol":"BTC","positionAmt":0.1,"entryPrice":67000.0,"unrealizedProfit":5.0,"side":"LONG"}
        get_reconciliation_engine().run(_sys(ex_pos=exch))
        events = get_event_bus().get_recent(limit=5)
        assert any(e["event"]=="RECONCILIATION_MISMATCH" for e in events)

    def test_singleton(self):
        from system_health.reconciliation import get_reconciliation_engine, reset_reconciliation_engine
        a = get_reconciliation_engine(); b = reset_reconciliation_engine()
        assert a is not b


# ════════════════════════════════════════════════════════════════════════════
# 3A — RecoveryEngine
# ════════════════════════════════════════════════════════════════════════════

class TestRecovery:
    def test_reconnect_ok(self):
        from system_health.recovery_engine import get_recovery_engine
        dp = MagicMock()
        dp._sync_time_offset = MagicMock()
        dp.get_account_balance.return_value = 10000.0
        assert get_recovery_engine().attempt_reconnect_data_provider({"data_provider":dp}) == "ok"

    def test_reconnect_no_provider(self):
        from system_health.recovery_engine import get_recovery_engine
        assert get_recovery_engine().attempt_reconnect_data_provider({}) == "no_provider"

    def test_cooldown_blocks_retry(self):
        from system_health.recovery_engine import get_recovery_engine
        dp = MagicMock(); dp._sync_time_offset=MagicMock(); dp.get_account_balance.return_value=1.0
        rec = get_recovery_engine(); s = {"data_provider":dp}
        r1=rec.attempt_reconnect_data_provider(s); r2=rec.attempt_reconnect_data_provider(s)
        assert r1=="ok" and r2=="skipped_cooldown"

    def test_cleanup_stale_mission(self):
        from system_health.recovery_engine import get_recovery_engine
        from missions.mission_tracker import get_mission_tracker
        rec = get_recovery_engine(); tracker = get_mission_tracker()
        m = tracker.create(symbol="BTCUSDT",direction="LONG",confidence=78.0)
        for stage in ("VALIDATION","RISK_CHECK","EXECUTION","MONITORING","CLOSED"):
            tracker.advance(m.id, stage)
        s = {"mission_tracker":tracker,"current_mission_id":m.id}
        assert rec.cleanup_stale_state(s) == "cleared"
        assert s["current_mission_id"] is None

    def test_no_auto_action_for_side_mismatch(self):
        from system_health.recovery_engine import get_recovery_engine
        from system_health.reconciliation import ReconciliationEvent
        evt = ReconciliationEvent(id="x",timestamp="2026-01-01T00:00:00Z",
            mismatch_type="SIDE_MISMATCH",exchange_view={},journal_view={},bot_view={},
            severity="critical",detail="test")
        r = get_recovery_engine().attempt_reconciliation_recovery(evt,{})
        assert "no_auto_recovery" in r

    def test_singleton(self):
        from system_health.recovery_engine import get_recovery_engine, reset_recovery_engine
        a=get_recovery_engine(); b=reset_recovery_engine()
        assert a is not b


# ════════════════════════════════════════════════════════════════════════════
# 3B — FeatureStore
# ════════════════════════════════════════════════════════════════════════════

def _feat(**kw):
    base={"direction":"LONG","confidence":78.0,"funding":0.0001,"open_interest":15000.0,
          "oi_delta":0.012,"liquidation_signal":0.0,"fear_greed":65.0,"regime":"TREND",
          "volatility":0.002,"atr":0.002,"smc_score":3.0,"volume_score":1.5,
          "entry_price":67000.0,"stop_loss":65800.0,"take_profit":69400.0}
    base.update(kw); return base

class TestFeatureStore:
    def test_save_and_get(self, db):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        rid = store.save_row(_feat(), mission_id="m1", trade_id=None)
        row = store.get_row(rid)
        assert row["direction"] == "LONG"
        assert row["confidence"] == 78.0
        assert row["result"] is None

    def test_extra_fields_go_to_json(self, db):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        rid = store.save_row(_feat(custom="hello"))
        assert store.get_row(rid)["extra_json"]["custom"] == "hello"

    def test_update_outcome(self, db):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        rid = store.save_row(_feat())
        assert store.update_outcome(rid, 1.0, 42.0, 3600.0)
        row = store.get_row(rid)
        assert row["result"] == 1.0 and row["pnl"] == 42.0

    def test_get_training_rows_excludes_unlabelled(self, db):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        labelled = store.save_row(_feat())
        store.update_outcome(labelled, 1.0, 10.0, 100.0)
        store.save_row(_feat())  # unlabelled
        assert len(store.get_training_rows()) == 1

    def test_count(self, db):
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        r1 = store.save_row(_feat()); r2 = store.save_row(_feat())
        store.update_outcome(r1, 1.0, 5.0, 100.0)
        assert store.count(labelled_only=False) == 2
        assert store.count(labelled_only=True)  == 1

    def test_trade_id_soft_reference_no_fk_error(self, db):
        """Regression: trade_id must NOT be a hard FK — capture must not fail
        if the trade row doesn't exist in the trades table yet."""
        from research.feature_store import FeatureStore
        store = FeatureStore(db_path=db)
        rid = store.save_row(_feat(), trade_id=99999)
        assert rid is not None
        assert store.get_row(rid)["trade_id"] == 99999


# ════════════════════════════════════════════════════════════════════════════
# 3B — trade_snapshot
# ════════════════════════════════════════════════════════════════════════════

class TestTradeSnapshot:
    def test_full_data(self):
        from research.trade_snapshot import build_feature_vector
        m = MagicMock(); m.direction="LONG"; m.confidence=78.0
        m.meta={"funding":0.0001,"oi_delta":0.012,"regime":"TREND"}
        tr = {"entry_price":67000.0,"stop_loss":65800.0,"take_profit":69400.0}
        mc = {"regime_data":{"atr_normalized":0.002},"smc_m15":{"score":3.0},
              "volume":{"score":1.5},"futures":{"liquidation":{"detected":True}}}
        intel = {"fear_greed":{"value":72},"liquidations":{"detected":True}}
        f = build_feature_vector(m, tr, mc, intel)
        assert f["direction"] == "LONG"
        assert f["confidence"] == 78.0
        assert f["liquidation_signal"] == 1.0
        assert f["fear_greed"] == 72.0

    def test_missing_everything_uses_defaults(self):
        from research.trade_snapshot import build_feature_vector
        f = build_feature_vector(None, None, None, None)
        assert f["direction"] == ""
        assert f["fear_greed"] == 50.0

    def test_never_raises(self):
        from research.trade_snapshot import build_feature_vector
        f = build_feature_vector(object(), None, None, None)
        assert isinstance(f, dict)

    def test_outcome_win(self):
        from research.trade_snapshot import build_outcome
        r,p,h = build_outcome({"result":"WIN","pnl":42.0})
        assert r == 1.0 and p == 42.0

    def test_outcome_loss(self):
        from research.trade_snapshot import build_outcome
        r,p,h = build_outcome({"result":"LOSS","pnl":-20.0})
        assert r == 0.0

    def test_outcome_open_is_none(self):
        from research.trade_snapshot import build_outcome
        r,p,h = build_outcome({"result":"OPEN"})
        assert r is None

    def test_outcome_holding_time(self):
        from research.trade_snapshot import build_outcome
        r,p,h = build_outcome({"result":"WIN","pnl":5.0,
            "timestamp":"2026-01-01T10:00:00+00:00","closed_at":"2026-01-01T11:00:00+00:00"})
        assert h == 3600.0


# ════════════════════════════════════════════════════════════════════════════
# 3B — DatasetBuilder
# ════════════════════════════════════════════════════════════════════════════

class TestDatasetBuilder:
    def test_capture_and_export(self, db):
        from research.feature_store import FeatureStore
        from research.dataset_builder import DatasetBuilder
        store = FeatureStore(db_path=db)
        builder = DatasetBuilder(store=store)
        m = MagicMock(); m.id="m1"; m.symbol="BTCUSDT"; m.direction="LONG"
        m.confidence=78.0; m.meta={}
        tr = {"id":1,"result":"WIN","pnl":42.0,"entry_price":67000.0}
        rid = builder.capture_closed_mission(mission=m, trade_row=tr)
        assert rid is not None
        assert builder.row_count(labelled_only=True) == 1

    def test_never_raises(self, db):
        from research.feature_store import FeatureStore
        from research.dataset_builder import DatasetBuilder
        builder = DatasetBuilder(store=FeatureStore(db_path=db))
        rid = builder.capture_closed_mission(mission=object(), trade_row=None)
        assert rid is None  # failed gracefully

    def test_export_returns_none_below_min(self, db):
        from research.feature_store import FeatureStore
        from research.dataset_builder import DatasetBuilder
        builder = DatasetBuilder(store=FeatureStore(db_path=db))
        assert builder.export_training_dataframe(min_rows=5) is None

    def test_export_dataframe_shape(self, db):
        from research.feature_store import FeatureStore
        from research.dataset_builder import DatasetBuilder
        store = FeatureStore(db_path=db)
        builder = DatasetBuilder(store=store)
        for i in range(15):
            rid = store.save_row(_feat()); store.update_outcome(rid, float(i%2), float(i), 100.0)
        df = builder.export_training_dataframe(min_rows=10)
        assert df is not None and len(df)==15
        assert "direction_enc" in df.columns and "regime_enc" in df.columns

    def test_singleton(self):
        from research.dataset_builder import get_dataset_builder, reset_dataset_builder
        a=get_dataset_builder(); b=reset_dataset_builder()
        assert a is not b


# ════════════════════════════════════════════════════════════════════════════
# 3C — Trainer
# ════════════════════════════════════════════════════════════════════════════

def _make_df(n=50):
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "direction_enc":      rng.choice([-1,1], n),
        "confidence":         rng.uniform(30,90,n),
        "funding":            rng.uniform(-0.001,0.001,n),
        "open_interest":      rng.uniform(10000,20000,n),
        "oi_delta":           rng.uniform(-0.05,0.05,n),
        "liquidation_signal": rng.choice([0.0,1.0], n),
        "fear_greed":         rng.uniform(20,80,n),
        "regime_enc":         rng.choice([0,1,2,3], n),
        "volatility":         rng.uniform(0.001,0.005,n),
        "atr":                rng.uniform(0.001,0.005,n),
        "smc_score":          rng.uniform(0,5,n),
        "volume_score":       rng.uniform(0,3,n),
        "result":             rng.choice([0.0,1.0], n),
        "pnl":                rng.uniform(-100,100,n),
    })

class TestTrainer:
    def test_train_meta_label_returns_model_and_metrics(self):
        from ml.trainer import train_meta_label
        r = train_meta_label(_make_df())
        assert r is not None
        model, metrics = r
        assert 0.0 <= metrics["win_rate"] <= 1.0
        assert "accuracy" in metrics

    def test_train_meta_label_too_few_rows(self):
        from ml.trainer import train_meta_label
        assert train_meta_label(_make_df(5)) is None

    def test_train_outcome_predictor(self):
        from ml.trainer import train_outcome_predictor
        r = train_outcome_predictor(_make_df())
        assert r is not None
        model, metrics = r
        assert 0.0 <= metrics.get("auc",0) <= 1.0


# ════════════════════════════════════════════════════════════════════════════
# 3C — Confidence Calibrator
# ════════════════════════════════════════════════════════════════════════════

class TestCalibrator:
    def test_train_isotonic(self):
        from ml.confidence_calibrator import train_calibrator, calibrate_confidence
        conf = list(np.linspace(10,90,40)); outcomes = [1 if c>50 else 0 for c in conf]
        cal = train_calibrator(conf, outcomes, method="isotonic")
        assert cal is not None
        result = calibrate_confidence(80.0, cal)
        assert 0.0 <= result <= 100.0

    def test_train_platt(self):
        from ml.confidence_calibrator import train_calibrator, calibrate_confidence
        conf = list(np.linspace(10,90,40)); outcomes = [1 if c>50 else 0 for c in conf]
        cal = train_calibrator(conf, outcomes, method="platt")
        assert cal is not None

    def test_none_calibrator_passthrough(self):
        from ml.confidence_calibrator import calibrate_confidence
        assert calibrate_confidence(75.0, None) == 75.0

    def test_too_few_samples_returns_none(self):
        from ml.confidence_calibrator import train_calibrator
        assert train_calibrator([50,60], [1,0]) is None


# ════════════════════════════════════════════════════════════════════════════
# 3C — Predictor
# ════════════════════════════════════════════════════════════════════════════

class TestPredictor:
    def test_meta_label_none_returns_trade(self):
        from ml.predictor import predict_meta_label
        assert predict_meta_label(None, {"direction":"LONG","confidence":70.0}) == "TRADE"

    def test_outcome_prob_none_returns_50(self):
        from ml.predictor import predict_outcome_probability
        assert predict_outcome_probability(None, {}) == 50.0

    def test_meta_label_with_real_model(self):
        from ml.trainer import train_meta_label
        from ml.predictor import predict_meta_label
        r = train_meta_label(_make_df(80))
        assert r is not None
        model, _ = r
        label = predict_meta_label(model, {"direction":"LONG","confidence":70.0,
            "funding":0.0001,"open_interest":15000.0,"oi_delta":0.012,
            "liquidation_signal":0.0,"fear_greed":65.0,"regime":"TREND",
            "volatility":0.002,"atr":0.002,"smc_score":3.0,"volume_score":1.5})
        assert label in ("TRADE","SKIP")

    def test_outcome_prob_range(self):
        from ml.trainer import train_outcome_predictor
        from ml.predictor import predict_outcome_probability
        r = train_outcome_predictor(_make_df(80))
        assert r is not None
        model, _ = r
        p = predict_outcome_probability(model, {"direction":"LONG","confidence":70.0,
            "funding":0.0001,"open_interest":15000.0,"oi_delta":0.012,
            "liquidation_signal":0.0,"fear_greed":65.0,"regime":"TREND",
            "volatility":0.002,"atr":0.002,"smc_score":3.0,"volume_score":1.5})
        assert 0.0 <= p <= 100.0


# ════════════════════════════════════════════════════════════════════════════
# 3C — MLAdvisor
# ════════════════════════════════════════════════════════════════════════════

class TestMLAdvisor:
    def _decision(self, action="LONG", conf=78.0):
        d = MagicMock()
        d.action = action; d.confidence = conf
        d.entry_price = 67000.0; d.stop_loss = 65800.0; d.take_profit = 69400.0
        d.block_reasons = []; d.blocked = False
        d.to_dict.return_value = {"action": action, "confidence": conf}
        return d

    def test_wait_decision_unchanged(self):
        from ml.ml_advisor import get_ml_advisor
        d = self._decision("WAIT")
        result = get_ml_advisor().advise(d, {})
        assert result.action == "WAIT"

    def test_none_decision_returned_unchanged(self):
        from ml.ml_advisor import get_ml_advisor
        assert get_ml_advisor().advise(None, {}) is None

    def test_never_raises(self):
        from ml.ml_advisor import get_ml_advisor
        d = self._decision("LONG")
        get_ml_advisor().advise(d, None)  # must not raise

    def test_skip_sets_action_to_wait(self, monkeypatch):
        from ml.ml_advisor import get_ml_advisor
        from ml import meta_label as ml_mod
        filt = MagicMock()
        filt.evaluate.return_value = ("SKIP", 30.0)
        monkeypatch.setattr(ml_mod, "get_meta_label_filter", lambda: filt)
        d = self._decision("LONG")
        get_ml_advisor().advise(d, {})
        assert d.action == "WAIT"
        assert d.blocked is True

    def test_trade_label_adjusts_confidence(self, monkeypatch):
        from ml.ml_advisor import get_ml_advisor
        from ml import meta_label as ml_mod
        from ml import confidence_calibrator as cc_mod
        filt = MagicMock(); filt.evaluate.return_value = ("TRADE", 75.0)
        monkeypatch.setattr(ml_mod, "get_meta_label_filter", lambda: filt)
        monkeypatch.setattr(cc_mod, "calibrate_confidence", lambda raw, _: raw + 5.0)
        d = self._decision("LONG", conf=70.0)
        # Ensure advisor._calibrator is set so calibrate is reached
        adv = get_ml_advisor()
        adv._calibrator = object()  # truthy non-None
        adv._calibrator_loaded = True
        adv.advise(d, {})
        assert abs(d.confidence - 75.0) < 1.0  # boosted by up to MAX_BOOST

    def test_singleton(self):
        from ml.ml_advisor import get_ml_advisor, reset_ml_advisor
        a=get_ml_advisor(); b=reset_ml_advisor()
        assert a is not b

    def test_status_dict_keys(self):
        from ml.ml_advisor import get_ml_advisor
        s = get_ml_advisor().status()
        assert "meta_label_active" in s
        assert "last_prediction" in s


# ════════════════════════════════════════════════════════════════════════════
# API endpoints
# ════════════════════════════════════════════════════════════════════════════

class TestPhase3API:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        from api.app import app
        return TestClient(app)

    def test_system_health_200(self, client):
        r = client.get("/api/system/health")
        assert r.status_code == 200
        assert "overall_status" in r.json()["data"]

    def test_system_health_reflects_heartbeat(self, client):
        from system_health.heartbeat import get_heartbeat
        get_heartbeat().beat("main_loop")
        r = client.get("/api/system/health")
        assert r.json()["data"]["subsystems"]["main_loop"]["status"] == "ALIVE"

    def test_system_reconciliation_200(self, client):
        r = client.get("/api/system/reconciliation")
        assert r.status_code == 200
        assert "events" in r.json()["data"]

    def test_ml_status_200(self, client):
        r = client.get("/api/ml/status")
        assert r.status_code == 200

    def test_ml_models_200(self, client):
        r = client.get("/api/ml/models")
        assert r.status_code == 200
        assert "meta_label" in r.json()["data"]

    def test_ml_performance_200(self, client):
        r = client.get("/api/ml/performance")
        assert r.status_code == 200
        d = r.json()["data"]
        assert "active_models" in d and "dataset" in d

    def test_existing_health_unchanged(self, client):
        """Backward compat: original /api/health contract must be untouched."""
        r = client.get("/api/health")
        assert r.status_code == 200
        assert "status" in r.json()["data"]


# ════════════════════════════════════════════════════════════════════════════
# main.py genuine integration (not mocks-only)
# ════════════════════════════════════════════════════════════════════════════

class TestMainIntegration:
    def _make_sys(self, action="WAIT"):
        from features.smc_engine import SMCSignals
        from features.volume_engine import VolumeSignals
        from missions.mission_tracker import get_mission_tracker
        from events.event_bus import get_event_bus
        from system_health.reconciliation import get_reconciliation_engine

        dp = MagicMock()
        dp.get_position_info.return_value = None
        dp.get_account_balance.return_value = 10_000.0
        dp.get_mark_price.return_value = 67000.0
        dp._sync_time_offset = MagicMock()
        dp.get_all_market_data.return_value = {
            "ohlcv": {"h1": MagicMock(),"h4": MagicMock(),"m15": MagicMock()},
            "funding_rate": 0.0001,"open_interest": 15000.0,"oi_delta": 0.012,
        }

        regime_r = MagicMock(); regime_r.regime="TREND"; regime_r.confidence=0.7
        regime_r.to_dict.return_value={"regime":"TREND","confidence":0.7}
        reg = MagicMock(); reg.classify.return_value=regime_r
        smc = MagicMock()
        smc.analyze_mtf.return_value={"m15":SMCSignals(),"h1":SMCSignals(),"h4":SMCSignals()}
        vol = MagicMock(); vol.analyze.return_value=VolumeSignals()
        ctxb = MagicMock()
        ctxb.build.return_value={
            "mtf_direction": action if action in ("LONG","SHORT") else "",
            "mtf_aligned": True,"mark_price": 67000.0,"regime":"TREND","futures":{}
        }

        decision = MagicMock()
        decision.action=action; decision.direction=action; decision.confidence=78.0
        decision.entry_price=67000.0; decision.stop_loss=65800.0; decision.take_profit=69400.0
        decision.regime="TREND"; decision.oi_delta=0.012; decision.funding_rate=0.0001
        decision.mtf_aligned=True; decision.raw_score=7; decision.breakdown={}
        decision.block_reasons=[]; decision.blocked=False
        decision.to_dict.return_value={"action":action,"confidence":78.0}
        ce = MagicMock(); ce.score.return_value=decision

        expl = MagicMock()
        er = MagicMock(); er.to_dict.return_value={"summary":"test"}
        expl.explain.return_value=er

        jrn = MagicMock()
        jrn.get_open_trades.return_value=[]; jrn.save_signal=MagicMock()
        jrn.save_market_regime=MagicMock(); jrn.save_funding=MagicMock()
        jrn.save_oi=MagicMock(); jrn.save_trade.return_value=1
        jrn.update_trade_result=MagicMock()

        rsk = MagicMock(); rsk.can_trade.return_value=(True,""); rsk.get_risk_pct.return_value=0.01
        # P1-B1: stub the new get_leverage(atr_pct=...) call — see test_commander.py
        # for why an un-stubbed MagicMock return value here breaks main.py.
        rsk.get_leverage.return_value = 5
        tm = MagicMock(); tm.execute_trade.return_value={"success":True,"quantity":0.1}

        return {
            "data_provider":dp,"smc_engine":smc,"volume_engine":vol,
            "regime_engine":reg,"context_builder":ctxb,"confidence_engine":ce,
            "causal_explainer":expl,"journal_v2":jrn,"risk_engine":rsk,
            "trade_manager":tm,"event_bus":get_event_bus(),"agent_layer":{},
            "mission_tracker":get_mission_tracker(),
            "reconciliation_engine":get_reconciliation_engine(),
            "current_mission_id":None,
        }

    def test_main_loop_heartbeat_fires(self):
        from main import run_trading_cycle
        from system_health.heartbeat import get_heartbeat
        run_trading_cycle(self._make_sys())
        assert get_heartbeat().get("main_loop") is not None

    def test_mission_and_telemetry_heartbeats_fire_on_wait(self):
        from main import run_trading_cycle
        from system_health.heartbeat import get_heartbeat
        run_trading_cycle(self._make_sys("WAIT"))
        hb = get_heartbeat()
        assert hb.get("mission_tracker") is not None
        assert hb.get("telemetry") is not None

    def test_trade_manager_heartbeat_fires_on_execution(self):
        from main import run_trading_cycle
        from system_health.heartbeat import get_heartbeat
        run_trading_cycle(self._make_sys("LONG"))
        assert get_heartbeat().get("trade_manager") is not None

    def test_monitor_loop_heartbeat_fires(self):
        from main import monitor_open_trades
        from system_health.heartbeat import get_heartbeat
        run_trading_cycle = None  # not needed
        monitor_open_trades(self._make_sys())
        assert get_heartbeat().get("monitor_loop") is not None

    def test_reconciliation_runs_via_scheduled_fn(self):
        from main import run_position_reconciliation
        sys = self._make_sys()
        run_position_reconciliation(sys)
        assert sys["reconciliation_engine"].status()["last_run"] is not None

    def test_reconciliation_never_raises_empty_sys(self):
        from main import run_position_reconciliation
        run_position_reconciliation({})

    def test_heartbeat_failure_does_not_break_cycle(self, monkeypatch):
        """Trading loop must survive if heartbeat module is broken."""
        import system_health.heartbeat as hb_mod
        monkeypatch.setattr(hb_mod, "get_heartbeat", lambda: (_ for _ in ()).throw(RuntimeError("broken")))
        from main import run_trading_cycle
        sys = self._make_sys("LONG")
        run_trading_cycle(sys)  # must not raise
        sys["trade_manager"].execute_trade.assert_called_once()

    def test_ml_advisor_failure_does_not_break_cycle(self, monkeypatch):
        """MLAdvisor crashing must not affect trade execution."""
        import ml.ml_advisor as adv_mod
        monkeypatch.setattr(adv_mod, "get_ml_advisor",
                            lambda: (_ for _ in ()).throw(RuntimeError("ml broken")))
        from main import run_trading_cycle
        sys = self._make_sys("LONG")
        run_trading_cycle(sys)
        sys["trade_manager"].execute_trade.assert_called_once()
