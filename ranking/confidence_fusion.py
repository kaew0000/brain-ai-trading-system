"""
ranking/confidence_fusion.py — V16 Phase 2 Part 2: composite scoring

Combines an eleven-factor ScoreBreakdown into one composite 0-100 score.

Key design choice: factors marked UNAVAILABLE (market_structure,
ai_confidence, historical_performance today — see score_breakdown.py) are
EXCLUDED from the weighted average and its weight redistributed across
the remaining computed factors, rather than folded in at their neutral-50
placeholder value. Including a neutral placeholder at full weight would
silently drag every symbol's composite toward 50 by the same amount,
which doesn't change relative ranking much but does make the absolute
score meaningless ("73" would actually mean "73, diluted by 40% unknown
data" with no way to tell). Excluding-and-renormalizing keeps the
composite score meaning "how good do the factors we actually measured
look", and `coverage` separately reports what fraction of the intended
signal was real vs. missing — callers (API/dashboard, once built) should
show both, not just the composite.
"""
from __future__ import annotations

from typing import Dict, Tuple

from config.settings import settings
from ranking.ranking_models import ScoreBreakdown, ScoreStatus


def fuse(breakdown: ScoreBreakdown, weights: Dict[str, float] = None) -> Tuple[float, float, str]:
    """
    Returns (composite_score, coverage, explanation).

    coverage: fraction (0-1) of total configured weight that was backed
    by a COMPUTED factor this cycle. 1.0 means every factor was real
    data; today's ceiling is well under 1.0 because three factors are
    always UNAVAILABLE until the follow-up work in
    opportunity_ranker.py's module docstring lands.
    """
    weights = weights or settings.RANKER_FACTOR_WEIGHTS

    total_weight = 0.0
    used_weight  = 0.0
    weighted_sum = 0.0
    computed_names = []
    unavailable_names = []

    for name, factor in breakdown.factors.items():
        w = weights.get(name, 0.0)
        factor.weight = w
        total_weight += w
        if factor.status == ScoreStatus.COMPUTED:
            weighted_sum += factor.score * w
            used_weight  += w
            computed_names.append(name)
        else:
            unavailable_names.append(name)

    composite = (weighted_sum / used_weight) if used_weight > 0 else 50.0
    coverage  = (used_weight / total_weight) if total_weight > 0 else 0.0

    top = sorted(
        (f for f in breakdown.factors.values() if f.status == ScoreStatus.COMPUTED),
        key=lambda f: f.score, reverse=True,
    )[:3]
    top_desc = ", ".join(f"{f.name}={f.score:.0f}" for f in top) if top else "no computed factors"

    explanation = (
        f"{breakdown.symbol}: composite {composite:.1f}/100 "
        f"(coverage {coverage*100:.0f}% — {len(computed_names)}/{len(breakdown.factors)} factors computed; "
        f"unavailable: {', '.join(unavailable_names) or 'none'}). Top drivers: {top_desc}."
    )
    return composite, coverage, explanation
