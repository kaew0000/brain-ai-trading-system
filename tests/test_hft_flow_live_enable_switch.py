"""tests/test_hft_flow_live_enable_switch.py — V16 Phase 4C Track B, HFT-6b.

Covers decision/confidence_engine.py::resolve_confidence_weights() and its
settings.HFT_FLOW_LIVE_ENABLED switch — the piece that closes the gap
HFT-6 deliberately left open ("nothing in this codebase reads
HFT_FLOW_LIVE_WEIGHT automatically"). This is the one new function added
by this phase; main.py's build_system() wiring
(`ConfidenceEngine(weights=resolve_confidence_weights())`) is a single
call site with no branching of its own, so it is intentionally not
re-tested end-to-end here — see tests/test_ceo_live_recommendation_wiring.py's
own docstring for the same "test the underlying function, not the wiring
line" convention used throughout this repo.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_default_returns_default_weights_object(monkeypatch):
    """Off by default (matches the shipped .env.example default) —
    resolve_confidence_weights() must return DEFAULT_WEIGHTS itself
    (or an equal copy) with hft_flow untouched at 0.0."""
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", False)

    result = resolve_confidence_weights()

    assert result == DEFAULT_WEIGHTS
    assert result["hft_flow"] == 0.0


def test_enabled_applies_live_weight(monkeypatch):
    """The core promise of this phase: flipping HFT_FLOW_LIVE_ENABLED
    (with HFT_FLOW_LIVE_WEIGHT at its default) actually raises the
    hft_flow slot, and nothing else changes."""
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 5.0)

    result = resolve_confidence_weights()

    assert result["hft_flow"] == 5.0
    for key in ("smc", "volume", "oi", "funding", "regime"):
        assert result[key] == DEFAULT_WEIGHTS[key]


def test_enabled_respects_custom_live_weight(monkeypatch):
    """Confirms the value is read from settings at call time, not
    hardcoded to the 5.0 default — e.g. a paper-lane operator using the
    HFT-5 paper-testing precedent of 20.0."""
    from config.settings import settings
    from decision.confidence_engine import resolve_confidence_weights
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 20.0)

    result = resolve_confidence_weights()

    assert result["hft_flow"] == 20.0


def test_default_weights_never_mutated(monkeypatch):
    """DEFAULT_WEIGHTS is a shared module-level constant relied on by
    tests/test_hft_flow_live_weight_config.py and
    tests/test_hft_shadow_mode.py — resolve_confidence_weights() must
    return a new dict, never mutate DEFAULT_WEIGHTS in place, regardless
    of the switch state."""
    from config.settings import settings
    from decision.confidence_engine import DEFAULT_WEIGHTS, resolve_confidence_weights

    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 999.0)
    resolve_confidence_weights()

    assert DEFAULT_WEIGHTS["hft_flow"] == 0.0


def test_confidence_engine_construction_with_resolved_weights(monkeypatch):
    """End-to-end at the ConfidenceEngine boundary (one level below
    main.py's wiring line): constructing with resolve_confidence_weights()
    output behaves exactly like the already-proven-safe
    test_hft_flow_live_weight_config.py::test_live_weight_only_takes_effect_via_explicit_opt_in
    pattern, whether the switch is on or off."""
    from config.settings import settings
    from decision.confidence_engine import ConfidenceEngine, resolve_confidence_weights

    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", False)
    engine_off = ConfidenceEngine(weights=resolve_confidence_weights())
    assert engine_off._weights["hft_flow"] == 0.0

    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_ENABLED", True)
    monkeypatch.setattr(settings, "HFT_FLOW_LIVE_WEIGHT", 5.0)
    engine_on = ConfidenceEngine(weights=resolve_confidence_weights())
    assert engine_on._weights["hft_flow"] > 0.0


def test_hft_flow_live_enabled_default_is_false():
    """Confirms the new setting's shipped default matches .env.example
    (false) — the whole feature stays inert on a fresh clone/config."""
    from config.settings import Settings
    s = Settings()
    assert s.HFT_FLOW_LIVE_ENABLED is False
