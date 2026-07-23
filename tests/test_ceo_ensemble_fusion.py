"""
Tests for CEOAgent Phase 4A — Ensemble Decision Engine fusion.

Covers:
  1. confidence_result is fused as a weighted vote, not an override —
     a strong agent-layer disagreement can outvote it.
  2. agreement_score reflects how split the agent layer is, and damps
     `confidence` accordingly.
  3. A ConfidenceEngine hard block (blocked=True / action="BLOCKED")
     still short-circuits to BLOCKED regardless of the vote.
  4. Risk manager veto still wins over a directional fusion result.

Uses hand-built FakeAgent stubs (not build_agent_layer's real engines) so
each contributing confidence/signal is exact and assertions are
deterministic, rather than depending on the bullish/bearish fixtures used
elsewhere in tests/test_agents.py.
"""

from __future__ import annotations

import pytest
from agents.base_agent import BaseAgent, AgentReport
from agents.ceo_agent import CEOAgent

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def reset_event_bus():
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


class FakeAgent(BaseAgent):
    """Stub agent that always returns a fixed AgentReport."""

    def __init__(self, name: str, signal: str, confidence: float, raw: dict = None):
        self.AGENT_NAME = name
        super().__init__()
        self._report = AgentReport(
            agent=name, signal=signal, confidence=confidence,
            summary=f"{name} says {signal}", raw=raw or {},
        )

    def analyse(self, market_context: dict) -> AgentReport:
        return self._report

    def answer(self, question: str, market_context=None) -> str:
        return "stub"


class FakeConfidenceResult:
    def __init__(self, action="WAIT", direction="", confidence=0.0,
                 blocked=False, block_reasons=None):
        self.action = action
        self.direction = direction
        self.confidence = confidence
        self.blocked = blocked
        self.block_reasons = block_reasons or []

    def to_dict(self):
        return {"action": self.action, "direction": self.direction,
                "confidence": self.confidence, "blocked": self.blocked}


def _ceo(**agent_reports) -> CEOAgent:
    """Build a CEOAgent with the given {key: FakeAgent} registered."""
    return CEOAgent(agents=agent_reports)


# ── 1. Fusion, not override ─────────────────────────────────────────────────

def test_agent_layer_can_outvote_confidence_engine():
    """
    Three agents (smc/futures/regime, weights .25+.20+.15=.60) vote SHORT
    at high confidence; ConfidenceEngine (weight .15) says LONG at 90%.
    Pre-4A this would have returned LONG (ConfidenceEngine always won).
    Post-4A the agent layer's weighted SHORT vote wins.
    """
    ceo = _ceo(
        smc     = FakeAgent("smc",     "SHORT", 90.0),
        futures = FakeAgent("futures", "SHORT", 90.0),
        regime  = FakeAgent("regime",  "SHORT", 90.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 100.0, raw={"can_trade": True}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    ce = FakeConfidenceResult(action="LONG", direction="LONG", confidence=90.0)
    dec = ceo.decide({}, confidence_result=ce)

    assert dec.action == "SHORT"
    assert dec.direction == "SHORT"


def test_confidence_engine_still_wins_when_agents_agree():
    """Sanity check: when agents and ConfidenceEngine agree, fusion still lands on that direction."""
    ceo = _ceo(
        smc     = FakeAgent("smc",     "LONG", 80.0),
        futures = FakeAgent("futures", "LONG", 80.0),
        regime  = FakeAgent("regime",  "LONG", 80.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 100.0, raw={"can_trade": True}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    ce = FakeConfidenceResult(action="LONG", direction="LONG", confidence=80.0)
    dec = ceo.decide({}, confidence_result=ce)

    assert dec.action == "LONG"
    assert dec.agreement_score == 1.0


# ── 2. Agreement / disagreement scoring ─────────────────────────────────────

def test_agreement_score_and_confidence_damping():
    """
    smc (LONG, w=.25) + futures (LONG, w=.20) vs regime (SHORT, w=.15), no
    confidence_result. long_score=45, short_score=15 -> LONG wins.
    agreement_score = (.25+.20)/(.25+.20+.15) = 0.75.
    Damped confidence = 45 * (0.5 + 0.5*0.75) = 39.375 -> 39.38.
    """
    ceo = _ceo(
        smc     = FakeAgent("smc",     "LONG",  100.0),
        futures = FakeAgent("futures", "LONG",  100.0),
        regime  = FakeAgent("regime",  "SHORT", 100.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 100.0, raw={"can_trade": True}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    dec = ceo.decide({})

    assert dec.action == "LONG"
    assert dec.agreement_score == pytest.approx(0.75, abs=1e-4)
    assert dec.confidence == pytest.approx(39.38, abs=0.01)
    assert any("AGREEMENT" in r for r in dec.reasons)


def test_unanimous_vote_has_no_damping():
    ceo = _ceo(
        smc     = FakeAgent("smc",     "LONG", 100.0),
        futures = FakeAgent("futures", "LONG", 100.0),
        regime  = FakeAgent("regime",  "LONG", 100.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 100.0, raw={"can_trade": True}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    dec = ceo.decide({})

    assert dec.action == "LONG"
    assert dec.agreement_score == 1.0
    # long_score = 100*.25 + 100*.20 + 100*.15(regime) = 60, undamped
    assert dec.confidence == pytest.approx(60.0, abs=0.01)


# ── 3. Hard block passthrough ───────────────────────────────────────────────

def test_confidence_engine_hard_block_vetoes_regardless_of_agent_votes():
    ceo = _ceo(
        smc     = FakeAgent("smc",     "LONG", 100.0),
        futures = FakeAgent("futures", "LONG", 100.0),
        regime  = FakeAgent("regime",  "LONG", 100.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 100.0, raw={"can_trade": True}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    ce = FakeConfidenceResult(action="BLOCKED", blocked=True,
                               block_reasons=["FUNDING_BLOCK_LONG rate=0.001"])
    dec = ceo.decide({}, confidence_result=ce)

    assert dec.action == "BLOCKED"
    assert any("hard block" in r for r in dec.reasons)


# ── 4. Risk veto still wins over fusion ─────────────────────────────────────

def test_risk_veto_wins_over_directional_fusion():
    ceo = _ceo(
        smc     = FakeAgent("smc",     "LONG", 100.0),
        futures = FakeAgent("futures", "LONG", 100.0),
        regime  = FakeAgent("regime",  "LONG", 100.0),
        risk    = FakeAgent("risk",    "NEUTRAL", 0.0, raw={"can_trade": False}),
        journal = FakeAgent("journal", "NEUTRAL", 0.0),
    )
    ce = FakeConfidenceResult(action="LONG", direction="LONG", confidence=95.0)
    dec = ceo.decide({}, confidence_result=ce)

    assert dec.action == "WAIT"
    assert dec.confidence == 0.0
    assert any("RISK_MANAGER" in r for r in dec.reasons)
