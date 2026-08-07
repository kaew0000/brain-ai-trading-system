"""
learning/application/ — V16 Phase 4C Step 3 (Track A): Recommendation
Application Layer.

Connects learning/'s (Phase 4C Step 1) recommendations to the live
decision pipeline as ADVISORY inputs only. Nothing in this package —
or in the additive hook it registers on CEOAgent
(agents/ceo_agent.py::decide_with_recommendations()) — opens a trade,
closes a trade, or overrides Risk Manager, Circuit Breaker, or a CEO
BLOCKED veto. See recommendation_advisor.py's module docstring for the
exact safety ordering.

Modules
-------
recommendation_validator  — Part A prereq: stamps validator_status.
recommendation_context    — Part A: filtering -> one canonical RecommendationSet.
recommendation_scoring    — Part D: deterministic 0.0-1.0 normalized score.
recommendation_advisor    — Part B + C: bounded decision-integration + explanations.
recommendation_metrics    — Part E: runtime counters.
recommendation_events     — Part G: EventBus publishing.
"""
from __future__ import annotations
