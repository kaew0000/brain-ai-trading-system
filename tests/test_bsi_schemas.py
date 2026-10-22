"""Schema validation: invalid/incomplete snapshots and records are rejected. (SYNTHETIC values.)"""

from datetime import UTC, datetime

import pytest
from tests._bsi_helpers import make_strategy
from pydantic import ValidationError

from brain_strategy_intelligence.schemas import Candle, MarketSnapshot, Recommendation, RiskContext

pytestmark = pytest.mark.unit

OK = dict(symbol="btcusdt", timestamp="2026-01-01T00:00:00", mark_price=100.0, regime="trend")


def test_snapshot_normalises_symbol_regime_and_naive_timestamp_is_utc():
    s = MarketSnapshot(**OK)
    assert s.symbol == "BTCUSDT" and s.regime == "TREND" and s.timestamp.tzinfo is UTC


@pytest.mark.parametrize(
    "bad",
    [
        dict(mark_price=0),
        dict(mark_price=-1),
        dict(mark_price=float("nan")),
        dict(symbol="bad sym!"),
        dict(timestamp="not-a-date"),
        dict(fear_greed=101),
        dict(regime_conf=1.5),
        dict(unknown_field=1),
        dict(open_interest=-5),
    ],
)
def test_invalid_snapshots_rejected(bad):
    with pytest.raises(ValidationError):
        MarketSnapshot(**{**OK, **bad})


def test_missing_fields_and_critical_missing_computed_by_code():
    s = MarketSnapshot(symbol="BTCUSDT", timestamp=datetime.now(UTC), mark_price=1.0)
    assert set(s.critical_missing()) == {"regime", "risk"}
    assert "funding_rate" in s.missing_fields()
    full = MarketSnapshot(**OK, risk=RiskContext(trading_allowed=True, max_leverage=1, risk_pct=0.01))
    assert full.critical_missing() == []


@pytest.mark.parametrize(
    "kw", [dict(high=9.0), dict(low=200.0), dict(open=-1.0), dict(close=float("inf")), dict(volume=-1.0)]
)
def test_invalid_candle_rejected(kw):
    base = dict(ts=1, open=10.0, high=11.0, low=9.0, close=10.5, volume=1.0)
    with pytest.raises(ValidationError):
        Candle(**{**base, **kw})


def test_recommendation_cannot_claim_execution_or_drop_advisory():
    with pytest.raises(ValidationError):
        Recommendation(status="OK", may_execute=True)
    with pytest.raises(ValidationError):
        Recommendation(status="OK", advisory_only=False)
    with pytest.raises(ValidationError):
        Recommendation(status="OK", order_size=1.0)  # no order fields exist


def test_strategy_rejects_secrets_bad_id_and_unvalidated_evidence_claims():
    with pytest.raises(ValidationError):
        make_strategy(description="use api_key=abcdef1234567890 for access")
    with pytest.raises(ValidationError):
        make_strategy(description="key " + "A" * 64)
    with pytest.raises(ValidationError):
        make_strategy(sid="Bad ID")
    with pytest.raises(ValidationError):
        make_strategy(validation_status="validated")  # no evidence id
    with pytest.raises(ValidationError):
        make_strategy(param_grid={"nope": [1, 2]})


def test_ai_generated_strategy_cannot_be_validated_without_human_approver():
    from brain_strategy_intelligence.schemas import Provenance

    ai = Provenance(source="llm", origin="ai_generated")
    with pytest.raises(ValidationError):
        make_strategy(provenance=ai, validation_status="validated", evidence_evaluation_id="abc")
    ok = make_strategy(provenance=ai, validation_status="validated", evidence_evaluation_id="abc", approved_by="human")
    assert ok.approved_by == "human"
