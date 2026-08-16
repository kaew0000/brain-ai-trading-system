"""tests/test_ceo_gated_signal_provider.py — V16 Phase 4B Step 3C: Live
CEO Agent Integration into Multi-Symbol Decision Pipeline

Covers Parts A (ExecutionOrchestrator integration contract), B (decision
mapping), C (feature flag), and E (journal) of this phase's brief.
"""
from __future__ import annotations

import pytest

from agents.ceo_agent import CEODecision
from execution.ceo_gated_signal_provider import (
    CEOGatedSignalProvider,
    map_ceo_decision_to_signal,
)
from execution.execution_orchestrator import ExecutionSignal

pytestmark = pytest.mark.unit


LONG_SIGNAL = ExecutionSignal(direction=1, entry_price=100.0, stop_loss=90.0, take_profit=110.0)
SHORT_SIGNAL = ExecutionSignal(direction=-1, entry_price=100.0, stop_loss=110.0, take_profit=90.0)


# ── Part B: centralized decision mapping (pure function) ──────────────────

class TestMapCeoDecisionToSignal:

    def test_long_agrees_with_priced_long_signal_confirms(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) == LONG_SIGNAL

    def test_short_agrees_with_priced_short_signal_confirms(self):
        decision = CEODecision(action="SHORT", direction="SHORT", confidence=80.0)
        assert map_ceo_decision_to_signal(decision, SHORT_SIGNAL) == SHORT_SIGNAL

    def test_long_disagrees_with_priced_short_signal_vetoes(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        assert map_ceo_decision_to_signal(decision, SHORT_SIGNAL) is None

    def test_short_disagrees_with_priced_long_signal_vetoes(self):
        decision = CEODecision(action="SHORT", direction="SHORT", confidence=80.0)
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) is None

    def test_wait_always_vetoes_regardless_of_underlying_signal(self):
        decision = CEODecision(action="WAIT")
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) is None
        assert map_ceo_decision_to_signal(decision, None) is None

    def test_blocked_always_vetoes_regardless_of_underlying_signal(self):
        """BLOCKED is the real fourth CEOAgent action — the brief's own
        mapping table named a 'REJECT' action that decide()/
        decide_from_context() can never actually produce (confirmed by
        reading agents/ceo_agent.py directly, not assumed)."""
        decision = CEODecision(action="BLOCKED")
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) is None
        assert map_ceo_decision_to_signal(decision, None) is None

    def test_long_with_no_underlying_signal_is_none(self):
        """CEODecision carries no entry/stop-loss/take-profit — there is
        nothing to confirm if the underlying pipeline priced nothing."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=90.0)
        assert map_ceo_decision_to_signal(decision, None) is None

    def test_none_decision_is_none(self):
        assert map_ceo_decision_to_signal(None, LONG_SIGNAL) is None

    def test_unrecognized_action_is_treated_as_veto_not_a_crash(self):
        decision = CEODecision(action="SOMETHING_ELSE")
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) is None

    def test_is_a_pure_function_no_side_effects(self):
        """Calling it twice with the same inputs gives the same output —
        no hidden state, no I/O."""
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        assert map_ceo_decision_to_signal(decision, LONG_SIGNAL) == map_ceo_decision_to_signal(decision, LONG_SIGNAL)


# ── Part C: feature flag ────────────────────────────────────────────────

class FakeSignalProvider:
    def __init__(self, signal=None):
        self.signal = signal
        self.get_signal_calls = []

    def get_signal(self, symbol):
        self.get_signal_calls.append(symbol)
        return self.signal


class FakeAdapter:
    def __init__(self, decision=None, signal=None):
        self.decision = decision
        self.signal = signal
        self.calls = []

    def decide_with_signal(self, symbol):
        self.calls.append(symbol)
        return self.decision, self.signal


class TestFeatureFlag:

    def test_disabled_is_byte_identical_passthrough(self):
        sp = FakeSignalProvider(signal=LONG_SIGNAL)
        adapter = FakeAdapter(decision=CEODecision(action="WAIT"), signal=None)
        gated = CEOGatedSignalProvider(sp, adapter, execution_lane="LIVE", enabled=False)

        result = gated.get_signal("BTCUSDT")

        assert result == LONG_SIGNAL  # exactly what the wrapped provider returned
        assert sp.get_signal_calls == ["BTCUSDT"]
        assert adapter.calls == []  # CEO pipeline never touched when disabled

    def test_enabled_routes_through_ceo_adapter_not_bare_signal_provider(self):
        sp = FakeSignalProvider(signal=LONG_SIGNAL)  # would be wrong if used directly
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(sp, adapter, execution_lane="LIVE", enabled=True)

        result = gated.get_signal("BTCUSDT")

        # V16 W14-2A: result is no longer byte-identical to LONG_SIGNAL —
        # get_signal() now also threads agent_attribution_from_ceo_decision()
        # onto the outgoing ExecutionSignal (see TestAttributionWiring
        # below for dedicated coverage of that new field). Compare the
        # pre-existing pricing/direction fields explicitly instead of
        # full dataclass equality, per this test's own original intent
        # (confirm the CEO-routed pricing came from `adapter`, not `sp`).
        assert result.direction == LONG_SIGNAL.direction
        assert result.entry_price == LONG_SIGNAL.entry_price
        assert result.stop_loss == LONG_SIGNAL.stop_loss
        assert result.take_profit == LONG_SIGNAL.take_profit
        assert adapter.calls == ["BTCUSDT"]
        assert sp.get_signal_calls == []  # bare get_signal() never called when enabled

    def test_default_reads_settings_live(self, monkeypatch):
        """No enabled= override: must read settings.CEO_MULTI_SYMBOL_ENABLED
        at call time, not at construction time — so flipping the setting
        takes effect on the next cycle without reconstructing this object."""
        from config import settings as settings_module

        sp = FakeSignalProvider(signal=LONG_SIGNAL)
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(sp, adapter, execution_lane="LIVE")  # no enabled= override

        monkeypatch.setattr(settings_module.settings, "CEO_MULTI_SYMBOL_ENABLED", False)
        gated.get_signal("BTCUSDT")
        assert adapter.calls == []  # disabled -> CEO not touched

        monkeypatch.setattr(settings_module.settings, "CEO_MULTI_SYMBOL_ENABLED", True)
        gated.get_signal("BTCUSDT")
        assert adapter.calls == ["BTCUSDT"]  # enabled -> CEO touched

    def test_default_disabled(self):
        from config.settings import Settings
        assert Settings().CEO_MULTI_SYMBOL_ENABLED is False


# ── Behavior when enabled: veto / confirm / error paths ───────────────────

class TestEnabledBehavior:

    def test_ceo_confirms_returns_the_priced_signal(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=85.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", enabled=True)
        result = gated.get_signal("BTCUSDT")
        # V16 W14-2A: agent_attribution is now populated (see
        # TestAttributionWiring below) — compare pricing fields only,
        # matching this test's original "priced signal" intent.
        assert result.direction == LONG_SIGNAL.direction
        assert result.entry_price == LONG_SIGNAL.entry_price
        assert result.stop_loss == LONG_SIGNAL.stop_loss
        assert result.take_profit == LONG_SIGNAL.take_profit

    def test_ceo_vetoes_by_disagreement_returns_none(self):
        decision = CEODecision(action="SHORT", direction="SHORT", confidence=85.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", enabled=True)
        assert gated.get_signal("BTCUSDT") is None

    def test_ceo_blocked_returns_none(self):
        decision = CEODecision(action="BLOCKED", confidence=0.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", enabled=True)
        assert gated.get_signal("BTCUSDT") is None

    def test_no_usable_symbol_this_cycle_returns_none(self):
        """decide_with_signal() itself returns (None, None) when the
        underlying pipeline has nothing this cycle (e.g. incomplete
        OHLCV) — must propagate cleanly, not crash."""
        adapter = FakeAdapter(decision=None, signal=None)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", enabled=True)
        assert gated.get_signal("BTCUSDT") is None

    def test_adapter_exception_is_caught_not_raised(self):
        class RaisingAdapter:
            def decide_with_signal(self, symbol):
                raise ConnectionError("simulated failure")

        gated = CEOGatedSignalProvider(FakeSignalProvider(), RaisingAdapter(), execution_lane="LIVE", enabled=True)
        result = gated.get_signal("BTCUSDT")  # must not raise
        assert result is None

    def test_call_dunder_matches_get_signal(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", enabled=True)
        assert gated("BTCUSDT") == gated.get_signal("BTCUSDT")


# ── Part E: journal (best-effort, non-fatal) ──────────────────────────────

class FakeJournal:
    def __init__(self, raise_on_save=False):
        self.saved = []
        self.raise_on_save = raise_on_save

    def save_agent_decision(self, **kwargs):
        if self.raise_on_save:
            raise RuntimeError("simulated DB failure")
        self.saved.append(kwargs)


class TestJournalPersistence:

    def test_disabled_stores_nothing(self):
        journal = FakeJournal()
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(signal=LONG_SIGNAL), adapter, execution_lane="LIVE", journal=journal, enabled=False)
        gated.get_signal("BTCUSDT")
        assert journal.saved == []

    def test_no_journal_supplied_does_not_raise(self):
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", journal=None, enabled=True)
        gated.get_signal("BTCUSDT")  # must not raise

    def test_enabled_with_decision_stores_ceo_action_confidence_reason(self):
        journal = FakeJournal()
        decision = CEODecision(
            action="LONG", direction="LONG", confidence=85.0,
            reasons=["SMC bullish", "funding negative"],
        )
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")

        assert len(journal.saved) == 1
        saved = journal.saved[0]
        assert saved["agent"] == "CEO_AGENT"
        assert saved["decision"] == "LONG"
        assert saved["symbol"] == "BTCUSDT"
        assert saved["score"] == 85.0
        assert saved["details"]["reasons"] == ["SMC bullish", "funding negative"]

    def test_journals_even_when_ceo_vetoes(self):
        """'when available' means whenever a CEODecision was produced —
        a vetoed trade is still a decision worth recording."""
        journal = FakeJournal()
        decision = CEODecision(action="WAIT", confidence=20.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")
        assert len(journal.saved) == 1
        assert journal.saved[0]["decision"] == "WAIT"

    def test_no_decision_this_cycle_stores_nothing(self):
        journal = FakeJournal()
        adapter = FakeAdapter(decision=None, signal=None)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", journal=journal, enabled=True)
        gated.get_signal("BTCUSDT")
        assert journal.saved == []

    def test_journal_write_failure_is_caught_not_raised(self):
        journal = FakeJournal(raise_on_save=True)
        decision = CEODecision(action="LONG", direction="LONG", confidence=80.0)
        adapter = FakeAdapter(decision=decision, signal=LONG_SIGNAL)
        gated = CEOGatedSignalProvider(FakeSignalProvider(), adapter, execution_lane="LIVE", journal=journal, enabled=True)
        result = gated.get_signal("BTCUSDT")  # must not raise
        # the trading decision itself still succeeds. V16 W14-2A:
        # agent_attribution is built in-process from ceo_decision (no
        # I/O), so it's still populated even though every journal write
        # above failed — compare pricing fields only, same reasoning as
        # the other two updated assertions in this file.
        assert result.direction == LONG_SIGNAL.direction
        assert result.entry_price == LONG_SIGNAL.entry_price
        assert result.stop_loss == LONG_SIGNAL.stop_loss
        assert result.take_profit == LONG_SIGNAL.take_profit
