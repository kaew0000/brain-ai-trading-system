"""tests/test_weighting_key_namespace.py — V16 §78.

Bug (raised in §76 / ROADMAP P1): Phase 4B dynamic per-agent weighting
(CEOAgent._effective_weights(), DYNAMIC_AGENT_WEIGHTS_ENABLED) looked an agent
up in journal.get_agent_performance() by its DISPLAY name (AgentReport.agent,
e.g. "SMC_ANALYST"). CEO-gated multi-symbol trades persist their votes under the
CEOAgent.WEIGHTS key ("smc") — both as agent_decisions.agent (Step 7C) and in the
explicit attribution (W14-2A). The names never matched, so with the flag on the
blend silently fell back to the static WEIGHTS for exactly the trades that drive
live multi-symbol decisions.

Fix (§78): journal/trade_attribution.py::WEIGHTS_KEY_ALIASES maps each WEIGHTS
key to the names its performance may be stored under (canonical key first, legacy
display name second); _effective_weights() merges the rows under those names
before applying the sample floor. Behind the existing flag, default OFF.

Which tests prove what:
  - TestMismatchThroughRealLifecycle, TestAliasMerge (canonical/split cases):
    FAIL on main with the flag forced on — they are the proof of the mismatch.
  - TestFlagOffZeroChange and the legacy-namespace cases: PASS on main and on the
    fix — invariant guards that nothing changes when the flag is off, and that the
    pre-existing single-namespace behavior is byte-identical when it is on.
  - TestNamespaceGuard: pins the alias table to CEOAgent.WEIGHTS and to the real
    agents' names so a third namespace cannot appear unnoticed (new API, so these
    fail on main by construction).

The lifecycle tests drive the same real path as tests/test_ceo_vote_persistence_
lifecycle.py (§76); only the CEO action is re-labelled LONG (the fixture market
always yields WAIT), agent_reports/weights_used stay the live layer's output.
"""
from __future__ import annotations

import pytest

from agents.base_agent import AgentReport, BaseAgent
from agents.ceo_agent import CEOAgent
from config.settings import settings
from events.event_bus import reset_event_bus
from execution.ceo_gated_signal_provider import CEOGatedSignalProvider
from journal.journal_v2 import TradeJournalV2
from tests.test_ceo_vote_persistence_lifecycle import (
    SYMBOL,
    _confirmed,
    _live_dispatcher,
    _NoExplicitAttribution,
    _open_and_close,
)

pytestmark = pytest.mark.unit

N_TRADES = 5          # closed WIN trades per lifecycle journal; also the sample floor
BLEND = 0.3


@pytest.fixture(autouse=True)
def _isolated_event_bus():
    reset_event_bus()
    yield
    reset_event_bus()


@pytest.fixture(scope="module")
def confirmed_decision():
    """ONE real CEODecision from the live 6-agent layer, re-labelled LONG."""
    reset_event_bus()
    decision, _ = _live_dispatcher().decide_with_signal(SYMBOL)
    reset_event_bus()
    return _confirmed(decision)


@pytest.fixture
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", True)
    monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_MIN_SAMPLES", N_TRADES)
    monkeypatch.setattr(settings, "DYNAMIC_WEIGHT_BLEND", BLEND)


@pytest.fixture
def flag_off(monkeypatch):
    monkeypatch.setattr(settings, "DYNAMIC_AGENT_WEIGHTS_ENABLED", False)


def _reports(decision) -> dict:
    """key -> AgentReport, exactly what CEOAgent._effective_weights() receives
    (note .agent is the DISPLAY name — that is the lookup name)."""
    return {
        k: AgentReport(agent=v["agent"], signal=v["signal"], confidence=v["confidence"])
        for k, v in decision.agent_reports.items()
    }


def _closed_trades_journal(tmp_path, decision, provider_cls, n=N_TRADES):
    journal = TradeJournalV2(db_path=str(tmp_path / "journal.db"))
    for _ in range(n):
        _open_and_close(journal, decision, provider_cls=provider_cls)
        reset_event_bus()
    return journal


class _FakeJournal:
    """The one method CEOAgent's dynamic weighting calls."""

    def __init__(self, rows=None):
        self._rows = rows or []
        self.call_count = 0

    def get_agent_performance(self, limit: int = 500):
        self.call_count += 1
        return self._rows


def _row(agent, total, wins):
    return {"agent": agent, "total_trades": total, "wins": wins, "losses": total - wins,
            "win_rate": round(wins / total, 4) if total else 0.0, "total_pnl": float(wins * 10 - (total - wins) * 10)}


def _legacy_effective_weights(rows_by_agent, reports, blend, min_n):
    """Independent oracle: the pre-§78 blend, lookup by AgentReport.agent only."""
    blended = {}
    for key, static_w in CEOAgent.WEIGHTS.items():
        rep = reports.get(key)
        perf = rows_by_agent.get(rep.agent) if rep is not None else None
        if perf is None or perf.get("total_trades", 0) < min_n:
            blended[key] = static_w
            continue
        blended[key] = static_w * ((1 - blend) + blend * (0.5 + float(perf.get("win_rate", 0.5))))
    total = sum(blended.values())
    return {k: v / total for k, v in blended.items()}


def _smc_reports():
    return {
        "smc": AgentReport(agent="SMC_ANALYST", signal="LONG", confidence=80.0),
        "futures": AgentReport(agent="FUTURES_ANALYST", signal="LONG", confidence=70.0),
    }


# ══════════════════════════════════════════════════════════════════════════
# 1. The mismatch, through the real §76 lifecycle (FAIL on main, flag forced on)
# ══════════════════════════════════════════════════════════════════════════

class TestMismatchThroughRealLifecycle:

    @pytest.mark.parametrize("provider_cls,cohort", [
        (CEOGatedSignalProvider, "post-W14-2A explicit attribution"),
        (_NoExplicitAttribution, "Step 7C-era agent_decisions join"),
    ])
    def test_winning_voters_gain_weight_from_ceo_gated_trades(
        self, tmp_path, confirmed_decision, flag_on, provider_cls, cohort,
    ):
        journal = _closed_trades_journal(tmp_path, confirmed_decision, provider_cls)
        eff = CEOAgent(journal=journal)._effective_weights(_reports(confirmed_decision))

        static = CEOAgent.WEIGHTS
        # smc and confidence_engine voted LONG on five LONG WINs -> win_rate 1.0 -> boosted
        assert eff["smc"] > static["smc"], cohort
        assert eff["confidence_engine"] > static["confidence_engine"], cohort
        # the neutral voters never matched the traded direction -> no record -> only renormalised down
        assert eff["futures"] < static["futures"], cohort
        assert sum(eff.values()) == pytest.approx(1.0)

    def test_decide_reports_the_learned_weights(self, tmp_path, confirmed_decision, flag_on):
        journal = _closed_trades_journal(tmp_path, confirmed_decision, CEOGatedSignalProvider)
        agents = {k: _FixedAgent(r) for k, r in _reports(confirmed_decision).items()}
        dec = CEOAgent(agents=agents, journal=journal).decide({})
        assert dec.weights_used["smc"] > round(CEOAgent.WEIGHTS["smc"], 4)


class _FixedAgent(BaseAgent):
    def __init__(self, report):
        self.AGENT_NAME = report.agent
        super().__init__()
        self._report = report

    def analyse(self, market_context):
        return self._report

    def answer(self, question, market_context=None):
        return "stub"


# ══════════════════════════════════════════════════════════════════════════
# 2. Alias merge semantics (fake journal rows)
# ══════════════════════════════════════════════════════════════════════════

class TestAliasMerge:

    def test_canonical_key_rows_are_found(self, flag_on):
        """Rows stored under the WEIGHTS key — how CEO-gated trades persist."""
        journal = _FakeJournal([_row("smc", N_TRADES, N_TRADES)])
        eff = CEOAgent(journal=journal)._effective_weights(_smc_reports())
        assert eff["smc"] > CEOAgent.WEIGHTS["smc"]

    def test_legacy_display_name_rows_are_still_found(self, flag_on):
        journal = _FakeJournal([_row("SMC_ANALYST", N_TRADES, N_TRADES)])
        eff = CEOAgent(journal=journal)._effective_weights(_smc_reports())
        assert eff["smc"] > CEOAgent.WEIGHTS["smc"]

    def test_split_namespaces_are_merged_before_the_sample_floor(self, flag_on):
        """3 trades under 'smc' (CEO-gated) + 3 under 'SMC_ANALYST' (legacy
        single-symbol): each alone is below the floor of 5, together they clear it.
        Weight must come from the MERGED counts (wins 3+2 of 6)."""
        rows = [_row("smc", 3, 3), _row("SMC_ANALYST", 3, 2)]
        eff = CEOAgent(journal=_FakeJournal(rows))._effective_weights(_smc_reports())

        merged_win_rate = round(5 / 6, 4)
        expected = _legacy_effective_weights(
            {"SMC_ANALYST": {"total_trades": 6, "win_rate": merged_win_rate}}, _smc_reports(), BLEND, N_TRADES,
        )
        assert eff["smc"] == pytest.approx(expected["smc"], rel=1e-9)
        assert eff["futures"] == pytest.approx(expected["futures"], rel=1e-9)

    def test_merged_total_below_floor_keeps_static(self, flag_on):
        rows = [_row("smc", 2, 2), _row("SMC_ANALYST", 2, 2)]   # 4 < 5
        eff = CEOAgent(journal=_FakeJournal(rows))._effective_weights(_smc_reports())
        assert eff == pytest.approx(CEOAgent.WEIGHTS)

    def test_aliases_never_leak_between_agents(self, flag_on):
        """'smc' rows must not move 'futures' (or the reverse)."""
        eff = CEOAgent(journal=_FakeJournal([_row("smc", N_TRADES, N_TRADES)]))._effective_weights(_smc_reports())
        # futures has no record of its own: only renormalisation moved it, never a boost
        assert eff["futures"] < CEOAgent.WEIGHTS["futures"]
        eff2 = CEOAgent(journal=_FakeJournal([_row("futures", N_TRADES, 0)]))._effective_weights(_smc_reports())
        assert eff2["futures"] < CEOAgent.WEIGHTS["futures"]      # 0% win rate -> cut
        assert eff2["smc"] > CEOAgent.WEIGHTS["smc"]              # renormalised up, not itself boosted

    def test_non_weights_agents_are_ignored(self, flag_on):
        """CEO_AGENT / ceo / trader rows are not WEIGHTS keys and must not matter."""
        rows = [_row("CEO_AGENT", 50, 50), _row("ceo", 50, 50), _row("trader", 50, 50), _row("TRADER", 50, 50)]
        eff = CEOAgent(journal=_FakeJournal(rows))._effective_weights(_smc_reports())
        assert eff == pytest.approx(CEOAgent.WEIGHTS)


# ══════════════════════════════════════════════════════════════════════════
# 3. Flag OFF: zero behavior change (invariant guards — pass on main too)
# ══════════════════════════════════════════════════════════════════════════

class TestFlagOffZeroChange:

    def test_flag_defaults_to_off(self):
        assert settings.model_fields["DYNAMIC_AGENT_WEIGHTS_ENABLED"].default is False
        assert settings.DYNAMIC_AGENT_WEIGHTS_ENABLED is False

    def test_off_returns_the_static_weights_object_and_never_queries(self, flag_off):
        journal = _FakeJournal([_row("smc", 100, 100), _row("SMC_ANALYST", 100, 100)])
        ceo = CEOAgent(journal=journal)
        assert ceo._effective_weights(_smc_reports()) is CEOAgent.WEIGHTS
        assert journal.call_count == 0

    def test_off_with_real_lifecycle_journal_is_static(self, tmp_path, confirmed_decision, flag_off):
        journal = _closed_trades_journal(tmp_path, confirmed_decision, CEOGatedSignalProvider)
        agents = {k: _FixedAgent(r) for k, r in _reports(confirmed_decision).items()}
        dec = CEOAgent(agents=agents, journal=journal).decide({})
        assert dec.weights_used == {k: round(v, 4) for k, v in CEOAgent.WEIGHTS.items()}

    def test_off_never_touches_the_alias_table(self, flag_off, monkeypatch):
        """If the lookup path ran with the flag off, a poisoned helper would blow up."""
        import journal.trade_attribution as ta
        if hasattr(ta, "aggregate_agent_performance"):
            monkeypatch.setattr(ta, "aggregate_agent_performance",
                                lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not be called when off")))
        journal = _FakeJournal([_row("smc", 100, 100)])
        assert CEOAgent(journal=journal)._effective_weights(_smc_reports()) is CEOAgent.WEIGHTS

    def test_on_without_a_journal_is_static(self, flag_on):
        assert CEOAgent(journal=None)._effective_weights(_smc_reports()) is CEOAgent.WEIGHTS

    def test_on_single_legacy_namespace_is_identical_to_the_pre_fix_formula(self, flag_on):
        """Flag ON but only display-name rows (the only case that worked before):
        output must equal the independent pre-§78 oracle exactly."""
        rows = [_row("SMC_ANALYST", 12, 9), _row("FUTURES_ANALYST", 30, 12), _row("CONFIDENCE_ENGINE", 7, 7)]
        reports = {
            **_smc_reports(),
            "confidence_engine": AgentReport(agent="CONFIDENCE_ENGINE", signal="LONG", confidence=60.0),
        }
        eff = CEOAgent(journal=_FakeJournal(rows))._effective_weights(reports)
        oracle = _legacy_effective_weights({r["agent"]: r for r in rows}, reports, BLEND, N_TRADES)
        assert eff.keys() == oracle.keys()
        for k in oracle:
            assert eff[k] == pytest.approx(oracle[k], rel=1e-12, abs=0)


# ══════════════════════════════════════════════════════════════════════════
# 4. One namespace, documented: the alias table cannot drift (new API)
# ══════════════════════════════════════════════════════════════════════════

class TestNamespaceGuard:

    def test_alias_keys_are_exactly_the_weights_keys(self):
        from journal.trade_attribution import CEO_WEIGHTED_AGENT_KEYS, WEIGHTS_KEY_ALIASES
        assert set(WEIGHTS_KEY_ALIASES) == set(CEOAgent.WEIGHTS) == set(CEO_WEIGHTED_AGENT_KEYS)

    def test_canonical_name_is_first_and_equals_the_key(self):
        from journal.trade_attribution import WEIGHTS_KEY_ALIASES
        for key, names in WEIGHTS_KEY_ALIASES.items():
            assert names[0] == key
            assert len(names) == len(set(names))

    def test_no_name_maps_to_two_weights_keys(self):
        from journal.trade_attribution import WEIGHTS_KEY_ALIASES
        flat = [n for names in WEIGHTS_KEY_ALIASES.values() for n in names]
        assert len(flat) == len(set(flat))

    def test_display_aliases_are_the_real_agents_names(self, confirmed_decision):
        """Pinned to what the live agent layer actually reports, not retyped."""
        from journal.trade_attribution import WEIGHTS_KEY_ALIASES
        for key in CEOAgent.WEIGHTS:
            assert confirmed_decision.agent_reports[key]["agent"] in WEIGHTS_KEY_ALIASES[key], key

    def test_aggregate_helper_cases(self):
        from journal.trade_attribution import aggregate_agent_performance as agg
        only = _row("smc", 4, 3)
        assert agg({}, "smc") is None
        assert agg({"smc": only}, "smc") is only                       # single row: returned untouched
        merged = agg({"smc": _row("smc", 3, 3), "SMC_ANALYST": _row("SMC_ANALYST", 3, 2)}, "smc")
        assert (merged["total_trades"], merged["wins"], merged["losses"]) == (6, 5, 1)
        assert merged["win_rate"] == round(5 / 6, 4)
        assert merged["total_pnl"] == round(30.0 + 10.0, 2)
        assert agg({"smc": only}, "futures") is None                    # no leakage
        # a name outside the table is only used when the caller passes it
        assert agg({"ODD_NAME": _row("ODD_NAME", 2, 2)}, "smc") is None
        assert agg({"ODD_NAME": _row("ODD_NAME", 2, 2)}, "smc", extra_names=("ODD_NAME",))["total_trades"] == 2
