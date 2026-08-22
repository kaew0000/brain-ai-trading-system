"""tests/test_hft_flow_live_weight_config.py — V16 Phase 4C Track B, HFT-6.

Covers config/settings.py::HFT_FLOW_LIVE_WEIGHT: confirms the setting
exists with its documented default, and — critically, since this phase
was explicitly scoped to "config value + docs only, no other new logic"
— that nothing in the codebase reads it automatically. DEFAULT_WEIGHTS in
decision/confidence_engine.py must still hardcode hft_flow at 0.0
regardless of this setting's value, and ConfidenceEngine's default
construction must remain fully unaffected by whatever this setting is
set to.
"""
import pytest

pytestmark = pytest.mark.unit


def test_hft_flow_live_weight_default_is_five():
    from config.settings import Settings
    s = Settings()
    assert s.HFT_FLOW_LIVE_WEIGHT == 5.0


def test_default_weights_unaffected_by_live_weight_setting(monkeypatch):
    """The core promise of this phase: changing HFT_FLOW_LIVE_WEIGHT must
    have zero automatic effect anywhere. DEFAULT_WEIGHTS is a hardcoded
    module-level constant, not settings-driven."""
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 999.0)
    assert DEFAULT_WEIGHTS["hft_flow"] == 0.0


def test_confidence_engine_default_construction_unaffected_by_live_weight(monkeypatch):
    from config.settings import settings
    from decision.confidence_engine import ConfidenceEngine
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 999.0)
    engine = ConfidenceEngine()
    assert engine._weights["hft_flow"] == 0.0


def test_live_weight_only_takes_effect_via_explicit_opt_in(monkeypatch):
    """Confirms the documented "Enabling for live" mechanism actually
    works when a person explicitly opts in — this is the one supported
    way this setting is meant to be used, exactly as documented in
    docs/architecture.md's HFT Flow Trend Following section."""
    from config.settings import settings
    from decision.confidence_engine import ConfidenceEngine, DEFAULT_WEIGHTS
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 5.0)

    live_weights = {**DEFAULT_WEIGHTS, "hft_flow": settings.HFT_FLOW_LIVE_WEIGHT}
    engine = ConfidenceEngine(weights=live_weights)
    assert engine._weights["hft_flow"] > 0.0

    # DEFAULT_WEIGHTS itself must remain untouched by constructing an
    # engine with a modified copy — dict unpacking must not have mutated
    # the shared module-level constant.
    assert DEFAULT_WEIGHTS["hft_flow"] == 0.0
