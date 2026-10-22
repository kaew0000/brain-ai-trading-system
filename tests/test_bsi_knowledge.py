"""SQLite persistence, retrieval, versioning, validation policy. (SYNTHETIC strategies.)"""

import pytest
from tests._bsi_helpers import make_strategy, synthetic_candles

from brain_strategy_intelligence.errors import DuplicateVersionError, StorageError, ValidationRefused
from brain_strategy_intelligence.evaluation.evaluator import StrategyEvaluator
from brain_strategy_intelligence.knowledge.repository import KnowledgeRepository
from brain_strategy_intelligence.knowledge.retrieval import Retriever
from brain_strategy_intelligence.knowledge.sqlite_store import SQLiteStrategyStore
from brain_strategy_intelligence.knowledge.vector_store import HashingEmbedder, cosine
from brain_strategy_intelligence.schemas import StrategyCategory, ValidationStatus

from tests._bsi_helpers import repo_fixture, cfg_fixture  # noqa: F401  (fixtures)

pytestmark = pytest.mark.unit


def test_persistence_survives_reopen(tmp_path):
    p = tmp_path / "k.sqlite3"
    r1 = KnowledgeRepository(SQLiteStrategyStore(p))
    r1.add_new(make_strategy("persist-me"))
    r1.store.close()
    r2 = KnowledgeRepository(SQLiteStrategyStore(p))
    got = r2.get("persist-me")
    assert got is not None and got.validation_status == ValidationStatus.UNVALIDATED
    assert r2.store.all_embeddings()  # embedding persisted too


def test_new_strategy_always_unvalidated_and_versions_are_immutable(repo):
    repo.add_new(make_strategy("a-1"))
    with pytest.raises(StorageError):
        repo.add_new(make_strategy("a-1"))  # same id again
    with pytest.raises(DuplicateVersionError):
        repo.store.add(make_strategy("a-1"), actor="t", reason="dup")


def test_revise_creates_new_version_resets_status_and_logs_history(repo):
    repo.add_new(make_strategy("rev-1"))
    cfg_eval = StrategyEvaluator.__module__  # noqa: F841 - import sanity
    s = repo.get("rev-1")
    repo.store.set_validation("rev-1", 1, ValidationStatus.REJECTED, None, None, "t", "test")
    v2 = repo.revise("rev-1", {"description": "changed text"}, actor="alice", reason="tweak")
    assert (
        v2.version == 2 and v2.validation_status == ValidationStatus.UNVALIDATED and v2.evidence_evaluation_id is None
    )
    assert repo.get("rev-1", 1).description == s.description  # old version intact
    hist = repo.history("rev-1")
    assert [h["action"] for h in hist] == ["add", "set_validation", "add"]
    assert hist[-1]["actor"] == "alice"


def test_revise_cannot_smuggle_validation_fields(repo):
    repo.add_new(make_strategy("rev-2"))
    with pytest.raises(StorageError):
        repo.revise("rev-2", {"validation_status": "validated"}, actor="x", reason="x")
    with pytest.raises(StorageError):
        repo.revise("missing", {}, actor="x", reason="x")


def test_failed_add_is_rolled_back_no_orphan_revision(repo):
    repo.add_new(make_strategy("tx-1"))
    n = len(repo.history("tx-1"))
    with pytest.raises(DuplicateVersionError):
        repo.store.add(make_strategy("tx-1"), actor="t", reason="dup")
    assert len(repo.history("tx-1")) == n


def test_keyword_regime_and_category_retrieval(repo):
    repo.add_new(make_strategy("trend-a", description="moving average trend following crossover"))
    repo.add_new(
        make_strategy(
            "range-b",
            category=StrategyCategory.MEAN_REVERSION,
            engine="rsi_reversion",
            parameters={"period": 14, "oversold": 30, "overbought": 70},
            description="oscillator mean reversion fade extremes",
            market_conditions=["RANGE"],
        )
    )
    r = Retriever(repo)
    assert r.search("moving average crossover")[0].strategy.id == "trend-a"
    assert [x.strategy.id for x in r.search("", regime="range")] == ["range-b"]
    assert [x.strategy.id for x in r.search("oscillator", category=StrategyCategory.MEAN_REVERSION)] == ["range-b"]
    assert r.search("zzzz-nothing-matches") == []
    assert r.search("trend", limit=0) == []


def test_rejected_strategies_hidden_by_default(repo):
    repo.add_new(make_strategy("bad-1", description="unique-token-xyz"))
    repo.reject("bad-1", 1, actor="t", reason="no edge")
    r = Retriever(repo)
    assert r.search("unique-token-xyz") == []
    assert len(r.search("unique-token-xyz", include_rejected=True)) == 1


def test_embedder_is_deterministic_and_similar_texts_score_higher():
    e = HashingEmbedder(128)
    a, b, c = (
        e.embed("trend following moving average"),
        e.embed("moving average trend"),
        e.embed("funding rate open interest"),
    )
    assert a == e.embed("trend following moving average")
    assert cosine(a, b) > cosine(a, c)


def test_record_evaluation_advances_only_to_backtested(repo, cfg):
    repo.add_new(make_strategy("ev-1"))
    ev = StrategyEvaluator(cfg).evaluate(
        repo.get("ev-1"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(test)"
    )
    assert ev.status == "COMPLETE"
    s = repo.record_evaluation(ev)
    assert s.validation_status == ValidationStatus.BACKTESTED and s.evidence_evaluation_id == ev.evaluation_id
    assert repo.store.latest_evaluation("ev-1", 1).evaluation_id == ev.evaluation_id


def test_incomplete_evaluation_never_advances_status(repo, cfg):
    repo.add_new(make_strategy("ev-2"))
    ev = StrategyEvaluator(cfg).evaluate(
        repo.get("ev-2"), synthetic_candles(100), symbol="SYNUSDT", timeframe="15m", data_label="SYNTHETIC(test)"
    )
    assert ev.status == "INCOMPLETE"
    assert repo.record_evaluation(ev).validation_status == ValidationStatus.UNVALIDATED


def test_mark_validated_policy(repo, cfg):
    repo.add_new(make_strategy("val-1"))
    repo.add_new(make_strategy("val-2"))
    ev = StrategyEvaluator(cfg).evaluate(
        repo.get("val-1"), synthetic_candles(), symbol="SYNUSDT", timeframe="15m", data_label="CSV:real.csv"
    )
    assert ev.status == "COMPLETE"
    with pytest.raises(ValidationRefused):
        repo.mark_validated("val-1", 1, ev, approved_by="", reason="x")  # approver required
    with pytest.raises(ValidationRefused):
        repo.mark_validated("val-2", 1, ev, approved_by="me", reason="x")  # wrong strategy
    with pytest.raises(ValidationRefused):
        repo.mark_validated(
            "val-1",
            1,
            ev.model_copy(update={"status": "INCOMPLETE", "incomplete_reasons": ["x"]}),
            approved_by="me",
            reason="x",
        )
    with pytest.raises(ValidationRefused):
        repo.mark_validated(
            "val-1", 1, ev.model_copy(update={"data_label": "SYNTHETIC(seed=1)"}), approved_by="me", reason="x"
        )
    out = repo.mark_validated("val-1", 1, ev, approved_by="nanthachai", reason="reviewed")
    assert out.validation_status == ValidationStatus.VALIDATED and out.approved_by == "nanthachai"
