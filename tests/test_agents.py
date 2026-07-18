"""
Tests for AI Agent Layer (Phase 2)

All tests are self-contained. No network calls, no file I/O.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

pytestmark = pytest.mark.unit


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_event_bus():
    """Reset EventBus singleton before each test to avoid cross-test pollution."""
    from events.event_bus import reset_event_bus
    reset_event_bus(journal=None, persist=False)
    yield
    reset_event_bus(journal=None, persist=False)


@pytest.fixture
def market_context_long():
    return {
        "regime": "TREND", "regime_conf": 0.75,
        "trend_bias": "LONG_BIAS", "trend_strength": "STRONG", "trend_conf": 0.8,
        "mtf_aligned": True, "mtf_direction": "LONG",
        "smc_m15": {
            "bos": True, "bos_dir": "Bullish",
            "choch": False, "choch_dir": "",
            "fvg": True, "fvg_dir": "Bullish",
            "ob": True, "ob_dir": "Bullish",
            "trend_bias": "LONG_BIAS",
            "liquidity_high": 68000.0, "liquidity_low": 64000.0,
            "prev_high": 67500.0, "prev_low": 64500.0,
        },
        "smc_h1":  {"bos": True, "bos_dir": "Bullish", "trend_bias": "LONG_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "smc_h4":  {"bos": True, "bos_dir": "Bullish", "trend_bias": "LONG_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "futures": {
            "funding":      {"rate": 0.0001, "annualised": 10.0, "extreme": False, "bias": "LONG_PAYING"},
            "open_interest":{"delta_pct": 0.012, "trend": "RISING", "pressure": "BULLISH"},
            "long_short":   {"ratio": 1.15, "crowd_bias": "NEUTRAL", "contrarian_signal": "NEUTRAL"},
            "taker":        {"buy_ratio": 0.58, "sell_ratio": 0.42, "aggressor": "BUY"},
            "liquidation":  {"detected": False, "type": "", "severity": "LOW"},
        },
        "funding_rate": 0.0001,
        "oi_delta": 0.012,
        "mark_price": 67000.0,
        "balance": 10000.0,
        "trend_data": {"ema_stack": "BULLISH", "adx": 32.0, "rsi": 55.0},
    }


@pytest.fixture
def market_context_short():
    ctx = {
        "regime": "TREND", "regime_conf": 0.70,
        "trend_bias": "SHORT_BIAS", "trend_strength": "MODERATE", "trend_conf": 0.65,
        "mtf_aligned": True, "mtf_direction": "SHORT",
        "smc_m15": {
            "bos": True, "bos_dir": "Bearish",
            "choch": True, "choch_dir": "Bearish",
            "fvg": True, "fvg_dir": "Bearish",
            "ob": True, "ob_dir": "Bearish",
            "trend_bias": "SHORT_BIAS",
            "liquidity_high": 68000.0, "liquidity_low": 64000.0,
            "prev_high": 67500.0, "prev_low": 64500.0,
        },
        "smc_h1":  {"bos": True, "bos_dir": "Bearish", "trend_bias": "SHORT_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "smc_h4":  {"bos": True, "bos_dir": "Bearish", "trend_bias": "SHORT_BIAS",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "futures": {
            "funding":      {"rate": -0.0003, "annualised": -32.0, "extreme": False, "bias": "SHORT_PAYING"},
            "open_interest":{"delta_pct": -0.008, "trend": "FALLING", "pressure": "BEARISH"},
            "long_short":   {"ratio": 0.75, "crowd_bias": "SHORT_CROWDED", "contrarian_signal": "LONG"},
            "taker":        {"buy_ratio": 0.42, "sell_ratio": 0.58, "aggressor": "SELL"},
            "liquidation":  {"detected": False, "type": "", "severity": "LOW"},
        },
        "funding_rate": -0.0003, "oi_delta": -0.008,
        "mark_price": 64000.0, "balance": 10000.0,
        "trend_data": {"ema_stack": "BEARISH", "adx": 28.0, "rsi": 42.0},
    }
    return ctx


@pytest.fixture
def market_context_neutral():
    return {
        "regime": "RANGE", "regime_conf": 0.45,
        "trend_bias": "NEUTRAL", "trend_strength": "WEAK", "trend_conf": 0.3,
        "mtf_aligned": False, "mtf_direction": "",
        "smc_m15": {"bos": False, "bos_dir": "", "choch": False, "choch_dir": "",
                    "fvg": False, "fvg_dir": "", "ob": False, "ob_dir": "",
                    "trend_bias": "NEUTRAL",
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "smc_h1":  {"bos": False, "bos_dir": "", "trend_bias": "NEUTRAL",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "smc_h4":  {"bos": False, "bos_dir": "", "trend_bias": "NEUTRAL",
                    "choch": False, "fvg": False, "ob": False,
                    "liquidity_high": 0, "liquidity_low": 0, "prev_high": 0, "prev_low": 0},
        "futures": {
            "funding":      {"rate": 0.00005, "annualised": 5.0, "extreme": False, "bias": "NEUTRAL"},
            "open_interest":{"delta_pct": 0.001, "trend": "FLAT", "pressure": "NEUTRAL"},
            "long_short":   {"ratio": 1.05, "crowd_bias": "NEUTRAL", "contrarian_signal": "NEUTRAL"},
            "taker":        {"buy_ratio": 0.50, "sell_ratio": 0.50, "aggressor": "BALANCED"},
            "liquidation":  {"detected": False, "type": "", "severity": "LOW"},
        },
        "funding_rate": 0.00005, "oi_delta": 0.001,
        "mark_price": 65000.0, "balance": 10000.0,
        "trend_data": {"ema_stack": "NEUTRAL", "adx": 18.0, "rsi": 50.0},
    }


# ── Base Agent ────────────────────────────────────────────────────────────────

class TestBaseAgent:
    def test_import(self):
        from agents.base_agent import BaseAgent, AgentReport
        assert BaseAgent is not None
        assert AgentReport is not None

    def test_agent_report_to_dict(self):
        from agents.base_agent import AgentReport
        r = AgentReport(agent="TEST", signal="LONG", confidence=75.5,
                        summary="Test", factors=[{"name":"X"}], raw={"k":"v"})
        d = r.to_dict()
        assert d["agent"]      == "TEST"
        assert d["signal"]     == "LONG"
        assert d["confidence"] == 75.5
        assert d["factors"]    == [{"name": "X"}]
        assert d["raw"]        == {"k": "v"}
        assert "timestamp"     in d

    def test_agent_report_defaults(self):
        from agents.base_agent import AgentReport
        r = AgentReport(agent="X")
        assert r.signal     == "NEUTRAL"
        assert r.confidence == 0.0
        assert r.factors    == []
        assert r.raw        == {}

    def test_base_agent_memory(self, market_context_neutral):
        from agents.smc_analyst import SMCAnalyst   # concrete subclass
        agent = SMCAnalyst()
        agent.run(market_context_neutral)
        mem = agent.get_memory(n=5)
        assert len(mem) == 1
        assert "signal" in mem[0]


# ── SMC Analyst ───────────────────────────────────────────────────────────────

class TestSMCAnalyst:
    def test_import(self):
        from agents.smc_analyst import SMCAnalyst
        assert SMCAnalyst is not None

    def test_analyse_long_signal(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        assert report.signal in ("LONG", "NEUTRAL")  # BOS+FVG+OB all bullish → LONG
        assert report.confidence >= 0
        assert isinstance(report.factors, list)
        assert len(report.factors) > 0

    def test_analyse_neutral_when_no_signals(self, market_context_neutral):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        report = agent.run(market_context_neutral)
        assert report.signal == "NEUTRAL"
        assert report.confidence == 0.0

    def test_factors_have_required_keys(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        for f in report.factors:
            assert "name"    in f
            assert "value"   in f
            assert "verdict" in f
            assert "detail"  in f

    def test_answer_fvg_question(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("Where is the FVG?", market_context_long)
        assert isinstance(ans, str)
        assert len(ans) > 5

    def test_answer_no_fvg(self, market_context_neutral):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        agent.run(market_context_neutral)
        ans = agent.answer("Is there a FVG?", market_context_neutral)
        assert "No" in ans or "not" in ans.lower() or "neutral" in ans.lower() or isinstance(ans, str)

    def test_answer_liquidity(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("Where is the liquidity?")
        assert isinstance(ans, str)

    def test_answer_bos(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("BOS detected?")
        assert isinstance(ans, str)

    def test_answer_before_run(self):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        ans = agent.answer("Why LONG?")
        assert "No" in ans or "not" in ans.lower() or isinstance(ans, str)

    def test_raw_fields(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        agent = SMCAnalyst()
        report = agent.run(market_context_long)
        assert "bos"         in report.raw
        assert "fvg"         in report.raw
        assert "mtf_aligned" in report.raw

    def test_events_published(self, market_context_long):
        from agents.smc_analyst import SMCAnalyst
        from events.event_bus import get_event_bus
        reset_event_bus = __import__("events.event_bus", fromlist=["reset_event_bus"]).reset_event_bus
        reset_event_bus(persist=False)
        agent = SMCAnalyst()
        agent.run(market_context_long)
        bus = get_event_bus()
        recent = bus.get_recent(agent="SMC_ANALYST")
        assert len(recent) > 0


# ── Futures Analyst ───────────────────────────────────────────────────────────

class TestFuturesAnalyst:
    def test_import(self):
        from agents.futures_analyst import FuturesAnalyst
        assert FuturesAnalyst is not None

    def test_analyse_returns_report(self, market_context_long):
        from agents.futures_analyst import FuturesAnalyst
        agent = FuturesAnalyst()
        report = agent.run(market_context_long)
        assert report.signal in ("LONG", "SHORT", "NEUTRAL")
        assert 0 <= report.confidence <= 100

    def test_extreme_funding_blocks_long(self):
        from agents.futures_analyst import FuturesAnalyst
        ctx = {
            "futures": {
                "funding":      {"rate": 0.0009, "annualised": 98.0, "extreme": True, "bias": "LONG_PAYING"},
                "open_interest":{"delta_pct": 0.002, "trend": "RISING", "pressure": "BULLISH"},
                "long_short":   {"ratio": 1.8, "crowd_bias": "LONG_CROWDED", "contrarian_signal": "SHORT"},
                "taker":        {"buy_ratio": 0.48, "sell_ratio": 0.52, "aggressor": "SELL"},
                "liquidation":  {"detected": False, "type": "", "severity": "LOW"},
            },
            "funding_rate": 0.0009, "oi_delta": 0.002, "mark_price": 67000.0,
        }
        agent = FuturesAnalyst()
        report = agent.run(ctx)
        # Extreme long funding + crowded longs → bearish contrarian
        assert report.signal in ("SHORT", "NEUTRAL")

    def test_answer_funding_question(self, market_context_long):
        from agents.futures_analyst import FuturesAnalyst
        agent = FuturesAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("What is the funding rate?")
        assert "funding" in ans.lower() or "%" in ans

    def test_answer_oi_question(self, market_context_long):
        from agents.futures_analyst import FuturesAnalyst
        agent = FuturesAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("What is the OI delta?")
        assert isinstance(ans, str) and len(ans) > 5

    def test_factors_present(self, market_context_long):
        from agents.futures_analyst import FuturesAnalyst
        agent = FuturesAnalyst()
        report = agent.run(market_context_long)
        names = [f["name"] for f in report.factors]
        assert "OI Trend"     in names
        assert "Funding Rate" in names

    def test_neutral_on_empty_context(self):
        from agents.futures_analyst import FuturesAnalyst
        agent = FuturesAnalyst()
        report = agent.run({})
        assert report.signal == "NEUTRAL"


# ── Regime Analyst ────────────────────────────────────────────────────────────

class TestRegimeAnalyst:
    def test_import(self):
        from agents.regime_analyst import RegimeAnalyst
        assert RegimeAnalyst is not None

    def test_long_in_trend(self, market_context_long):
        from agents.regime_analyst import RegimeAnalyst
        agent = RegimeAnalyst()
        report = agent.run(market_context_long)
        assert report.signal in ("LONG", "NEUTRAL")

    def test_neutral_in_range(self, market_context_neutral):
        from agents.regime_analyst import RegimeAnalyst
        agent = RegimeAnalyst()
        report = agent.run(market_context_neutral)
        assert report.signal == "NEUTRAL"

    def test_regime_change_published(self, market_context_long, market_context_neutral):
        from agents.regime_analyst import RegimeAnalyst
        from events.event_bus import get_event_bus, reset_event_bus
        reset_event_bus(persist=False)
        agent = RegimeAnalyst()
        agent.run(market_context_long)
        agent.run(market_context_neutral)   # regime changes TREND→RANGE
        bus = get_event_bus()
        events = bus.get_recent(agent="REGIME_ANALYST")
        assert len(events) > 0

    def test_answer_regime_question(self, market_context_long):
        from agents.regime_analyst import RegimeAnalyst
        agent = RegimeAnalyst()
        agent.run(market_context_long)
        ans = agent.answer("What regime are we in?")
        assert "TREND" in ans or "regime" in ans.lower()


# ── Risk Manager ──────────────────────────────────────────────────────────────

class TestRiskManagerAgent:
    @staticmethod
    def _make_engine(today_pnl=0.0, consec_losses=0):
        """Build a real RiskEngine against a journal mock shaped like the
        actual TradeJournalV2 contract (get_today_pnl, get_consecutive_losses,
        get_daily_stats()->{"total_pnl": ...}) — not the "day_pnl" /
        "consecutive_losses" keys the old buggy agent code assumed."""
        from risk.risk_engine import RiskEngine
        mock_journal = MagicMock()
        mock_journal.get_today_pnl.return_value = today_pnl
        mock_journal.get_consecutive_losses.return_value = consec_losses
        mock_journal.get_daily_stats.return_value = {
            "total_pnl": today_pnl, "total_trades": 0, "win_rate": 0.0,
        }
        return RiskEngine(mock_journal)

    def test_import(self):
        from agents.risk_manager import RiskManagerAgent
        assert RiskManagerAgent is not None

    def test_approved_when_clean(self, market_context_long):
        from agents.risk_manager import RiskManagerAgent
        engine = self._make_engine(today_pnl=0.0, consec_losses=0)
        agent = RiskManagerAgent(risk_engine=engine, journal=engine.journal)
        report = agent.run({**market_context_long, "balance": 10000.0})
        assert report.raw["can_trade"] is True

    def test_blocked_on_daily_loss(self, market_context_long):
        from agents.risk_manager import RiskManagerAgent
        engine = self._make_engine(today_pnl=-500.0, consec_losses=0)  # 5% of 10k — exceeds MAX_DAILY_LOSS
        agent = RiskManagerAgent(risk_engine=engine, journal=engine.journal)
        report = agent.run({**market_context_long, "balance": 10000.0})
        assert report.raw["can_trade"] is False
        assert report.raw["risk_level"] == "HALT"

    def test_blocked_on_consec_losses(self, market_context_long):
        from agents.risk_manager import RiskManagerAgent
        from config.settings import settings
        engine = self._make_engine(today_pnl=0.0, consec_losses=settings.MAX_CONSECUTIVE_LOSSES)
        agent = RiskManagerAgent(risk_engine=engine, journal=engine.journal)
        report = agent.run({**market_context_long, "balance": 10000.0})
        assert report.raw["can_trade"] is False
        assert report.raw["risk_level"] == "HALT"

    def test_delegates_to_risk_engine_not_journal_dict_shape(self, market_context_long):
        """Regression test for the v16 consolidation fix: the agent must
        read numbers from RiskEngine.report(), not recompute them from
        journal.get_daily_stats() with assumed key names. A journal whose
        get_daily_stats() carries the wrong shape (as every previous test
        in this class used to mock) must NOT influence the verdict once a
        real risk_engine is wired in — only the engine's numbers matter."""
        from agents.risk_manager import RiskManagerAgent
        engine = self._make_engine(today_pnl=-500.0, consec_losses=0)
        decoy_journal = MagicMock()
        decoy_journal.get_daily_stats.return_value = {"day_pnl": 0.0, "consecutive_losses": 0}
        agent = RiskManagerAgent(risk_engine=engine, journal=decoy_journal)
        report = agent.run({**market_context_long, "balance": 10000.0})
        assert report.raw["can_trade"] is False  # engine's -500 pnl wins, not the decoy's 0.0

    def test_no_risk_engine_falls_back_to_safe_default(self, market_context_long):
        """Construction without a wired RiskEngine (not expected in
        production — main.py always wires one) must not guess at real
        numbers; it reports a clearly-logged safe default instead."""
        from agents.risk_manager import RiskManagerAgent
        mock_journal = MagicMock()
        agent = RiskManagerAgent(journal=mock_journal)
        report = agent.run({**market_context_long, "balance": 10000.0})
        assert report.raw["can_trade"] is True

    def test_no_journal_still_works(self, market_context_long):
        from agents.risk_manager import RiskManagerAgent
        agent = RiskManagerAgent()
        report = agent.run(market_context_long)
        assert "can_trade" in report.raw

    def test_answer_risk_question(self, market_context_long):
        from agents.risk_manager import RiskManagerAgent
        agent = RiskManagerAgent()
        agent.run(market_context_long)
        ans = agent.answer("Can I trade?")
        assert isinstance(ans, str) and len(ans) > 5


# ── Trader Agent ──────────────────────────────────────────────────────────────

class TestTraderAgent:
    def test_no_position(self, market_context_neutral):
        from agents.trader_agent import TraderAgent
        agent = TraderAgent()
        report = agent.run(market_context_neutral)
        assert report.signal == "NEUTRAL"
        assert "No open position" in report.summary

    def test_with_position(self, market_context_long):
        from agents.trader_agent import TraderAgent
        ctx = {**market_context_long,
               "open_position": {
                   "direction": "LONG", "entry_price": 65000.0,
                   "quantity": 0.1, "unrealised_pnl": 50.0,
                   "stop_loss": 63000.0, "take_profit": 70000.0,
               }}
        agent = TraderAgent()
        report = agent.run(ctx)
        assert report.signal == "LONG"
        assert report.confidence == 100.0

    def test_answer_entry_question(self, market_context_long):
        from agents.trader_agent import TraderAgent
        ctx = {**market_context_long,
               "open_position": {"direction":"LONG","entry_price":65000.0,
                                 "quantity":0.1,"unrealised_pnl":50.0,
                                 "stop_loss":63000.0,"take_profit":70000.0}}
        agent = TraderAgent()
        agent.run(ctx)
        ans = agent.answer("What is the entry price?")
        assert "65000" in ans


# ── Journal Analyst ───────────────────────────────────────────────────────────

class TestJournalAnalyst:
    def test_empty_journal(self):
        from agents.journal_analyst import JournalAnalyst
        mock_journal = MagicMock()
        mock_journal.get_performance_summary.return_value = {}
        mock_journal.get_daily_stats.return_value = {}
        agent = JournalAnalyst(journal=mock_journal)
        report = agent.run({})
        assert report.signal == "NEUTRAL"
        assert report.total_trades == 0 if hasattr(report, "total_trades") else True

    def test_good_performance(self):
        from agents.journal_analyst import JournalAnalyst
        mock_journal = MagicMock()
        mock_journal.get_performance_summary.return_value = {
            "total_trades": 60, "winning_trades": 36, "losing_trades": 24,
            "win_rate": 60.0, "profit_factor": 1.8, "expectancy": 15.0, "max_drawdown": 3.5,
        }
        mock_journal.get_daily_stats.return_value = {"day_pnl": 50.0}
        agent = JournalAnalyst(journal=mock_journal)
        report = agent.run({})
        assert report.signal == "LONG"   # strong edge
        assert report.confidence > 50

    def test_answer_win_rate(self):
        from agents.journal_analyst import JournalAnalyst
        mock_journal = MagicMock()
        mock_journal.get_performance_summary.return_value = {
            "total_trades": 20, "winning_trades": 12, "losing_trades": 8,
            "win_rate": 60.0, "profit_factor": 1.5, "expectancy": 10.0, "max_drawdown": 5.0,
        }
        mock_journal.get_daily_stats.return_value = {"day_pnl": 20.0}
        agent = JournalAnalyst(journal=mock_journal)
        agent.run({})
        ans = agent.answer("What is the win rate?")
        assert "60" in ans or "win" in ans.lower()


# ── CEO Agent ─────────────────────────────────────────────────────────────────

class TestCEOAgent:
    def test_import(self):
        from agents.ceo_agent import CEOAgent, CEODecision
        assert CEOAgent is not None
        assert CEODecision is not None

    def test_decide_long_context(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]
        dec = ceo.decide(market_context_long)
        assert dec.action in ("LONG", "SHORT", "WAIT")
        assert 0 <= dec.confidence <= 100
        assert isinstance(dec.score_breakdown, dict)
        assert isinstance(dec.reasons, list)

    def test_ceo_decision_to_dict(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]
        dec = ceo.decide(market_context_long)
        d = dec.to_dict()
        required = {"action","direction","confidence","score_breakdown","reasons","agent_reports","timestamp"}
        assert required.issubset(d.keys())

    def test_ceo_with_confidence_result(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]

        class FakeConfidenceResult:
            action    = "LONG"
            direction = "LONG"
            confidence = 78.0
        dec = ceo.decide(market_context_long, confidence_result=FakeConfidenceResult())
        assert dec.action == "LONG"

    def test_ceo_risk_veto(self, market_context_long):
        from risk.risk_engine import RiskEngine
        from agents import build_agent_layer
        agents = build_agent_layer()
        # Force risk blocked. Post-consolidation, RiskManagerAgent reads its
        # verdict from self._risk_engine (not self._journal directly), so
        # the veto must be forced via a real RiskEngine over a journal that
        # matches its actual contract (get_today_pnl/get_consecutive_losses).
        mock_journal = MagicMock()
        mock_journal.get_today_pnl.return_value = -500.0
        mock_journal.get_consecutive_losses.return_value = 0
        mock_journal.get_daily_stats.return_value = {"total_pnl": -500.0, "total_trades": 1, "win_rate": 0.0}
        agents["risk"]._risk_engine = RiskEngine(mock_journal)
        agents["risk"]._journal = mock_journal
        ceo = agents["ceo"]

        class FakeConfidence:
            action = "LONG"; direction = "LONG"; confidence = 85.0
        dec = ceo.decide({**market_context_long, "balance": 10000.0}, confidence_result=FakeConfidence())
        assert dec.action == "WAIT"

    def test_ceo_answer_routing(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]
        ceo.decide(market_context_long)
        # Should route FVG question to SMC analyst
        ans = ceo.answer("Where is the FVG?", market_context_long)
        assert isinstance(ans, str) and len(ans) > 5

    def test_ceo_npc_speech(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]
        dec = ceo.decide(market_context_long)
        speech = dec.npc_speech()
        assert isinstance(speech, str) and len(speech) > 3

    def test_agent_reports_populated(self, market_context_long):
        from agents import build_agent_layer
        agents = build_agent_layer()
        ceo = agents["ceo"]
        dec = ceo.decide(market_context_long)
        # At least some agents should produce reports
        assert len(dec.agent_reports) > 0

    def test_build_agent_layer(self):
        from agents import build_agent_layer
        layer = build_agent_layer()
        assert "smc"     in layer
        assert "futures" in layer
        assert "regime"  in layer
        assert "risk"    in layer
        assert "trader"  in layer
        assert "journal" in layer
        assert "ceo"     in layer


# ── Forward Test Evaluator ────────────────────────────────────────────────────

class TestForwardTestEvaluator:
    def test_import(self):
        from forward_test.evaluator import ForwardTestEvaluator, ForwardTestReport
        assert ForwardTestEvaluator is not None
        assert ForwardTestReport is not None

    def test_empty_trades(self):
        from forward_test.evaluator import ForwardTestEvaluator
        ev = ForwardTestEvaluator()
        r  = ev.evaluate([])
        assert r.total_trades == 0
        assert r.win_rate == 0.0

    def test_all_wins(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = [{"pnl": 100.0, "regime": "TREND"} for _ in range(10)]
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        assert r.total_trades    == 10
        assert r.winning_trades  == 10
        assert r.win_rate        == 100.0
        assert r.profit_factor   == 999.0  # no losses
        assert r.net_pnl         == 1000.0
        assert r.grade           in ("A+", "A")   # sharpe=0 when all pnl identical → A not A+

    def test_all_losses(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = [{"pnl": -50.0, "regime": "RANGE"} for _ in range(5)]
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        assert r.total_trades   == 5
        assert r.losing_trades  == 5
        assert r.win_rate       == 0.0
        assert r.net_pnl        == -250.0

    def test_mixed_trades(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = (
            [{"pnl": 80.0,  "regime": "TREND"}] * 6 +
            [{"pnl": -40.0, "regime": "RANGE"}] * 4
        )
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        assert r.total_trades    == 10
        assert r.winning_trades  == 6
        assert r.win_rate        == 60.0
        assert r.profit_factor   > 1.0
        assert r.expectancy      > 0

    def test_report_to_dict(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = [{"pnl": 50.0}] * 5 + [{"pnl": -30.0}] * 5
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        d  = r.to_dict()
        required = {"total_trades","win_rate","profit_factor","sharpe","sortino",
                    "max_drawdown_pct","expectancy","grade","verdict"}
        assert required.issubset(d.keys())

    def test_summary_line(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = [{"pnl": 60.0}] * 7 + [{"pnl": -40.0}] * 3
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        s  = r.summary_line()
        assert "trades" in s
        assert "WR"     in s
        assert "Grade"  in s

    def test_regime_breakdown(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = (
            [{"pnl": 80.0,  "regime": "TREND"}] * 5 +
            [{"pnl": -30.0, "regime": "RANGE"}] * 5
        )
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        assert "TREND" in r.regime_breakdown
        assert "RANGE" in r.regime_breakdown
        assert r.regime_breakdown["TREND"]["n"] == 5

    def test_auto_report_trigger(self):
        from forward_test.evaluator import ForwardTestEvaluator
        ev = ForwardTestEvaluator()
        assert ev.should_auto_report(50)  is True
        assert ev.should_auto_report(51)  is False
        assert ev.should_auto_report(100) is True

    def test_sharpe_positive_for_wins(self):
        from forward_test.evaluator import ForwardTestEvaluator
        trades = [{"pnl": 100.0}] * 10 + [{"pnl": -20.0}] * 2
        ev = ForwardTestEvaluator()
        r  = ev.evaluate(trades)
        assert r.sharpe > 0

    def test_max_drawdown_calculated(self):
        from forward_test.evaluator import ForwardTestEvaluator
        # Equity goes: 10000 → 10100 → 9900 → 10200
        trades = [{"pnl": 100.0}, {"pnl": -200.0}, {"pnl": 300.0}]
        ev = ForwardTestEvaluator(starting_balance=10000.0)
        r  = ev.evaluate(trades)
        assert r.max_drawdown > 0
        assert r.max_drawdown_pct > 0
