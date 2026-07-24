"""
ranking/ranking_models.py — V16 Phase 2 Part 2: Opportunity Ranking Engine

Data models only — no scoring logic here (see score_breakdown.py /
confidence_fusion.py), no Binance/network access, no persistence.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from enum import Enum


class ScoreStatus(str, Enum):
    """
    Whether a factor score reflects a real computation from available
    data, or a placeholder because the required input isn't available
    from the scanner cache. UNAVAILABLE is a first-class, visible state —
    never silently defaulted to a number that looks like a real score.
    """
    COMPUTED     = "computed"
    UNAVAILABLE  = "unavailable"


@dataclass
class FactorScore:
    """One scored factor (e.g. 'trend', 'funding') for one symbol."""
    name:        str
    score:       float          # 0-100, higher = more favorable
    status:      ScoreStatus
    explanation: str
    raw_value:   float | None = None   # the underlying metric, if any (e.g. atr_pct)
    weight:      float = 0.0              # weight actually applied during fusion

    def to_dict(self) -> dict:
        d = asdict(self)
        d["status"] = self.status.value
        return d


@dataclass
class ScoreBreakdown:
    """All factor scores for one symbol, keyed by factor name."""
    symbol:  str
    factors: dict[str, FactorScore] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "factors": {k: v.to_dict() for k, v in self.factors.items()},
        }


@dataclass
class RankedOpportunity:
    """One row of the final Top-N ranked output."""
    rank:          int
    symbol:        str
    composite_score: float        # 0-100
    breakdown:     ScoreBreakdown
    explanation:   str            # human-readable one-liner summarizing why it ranked here
    ranked_at:     float          # unix epoch
    data_age_s:    float          # how stale the underlying scanner snapshot was, seconds
    # V16 Phase 2A addition: previously computed by confidence_fusion.fuse()
    # and only used inside its own explanation string, then discarded.
    # portfolio/capital_manager.py needs it as real data (see its module
    # docstring for why coverage replaces the brief's requested-but-
    # UNAVAILABLE "AI Confidence" input) — additive field, defaults to 1.0
    # so any existing RankedOpportunity(...) construction site that
    # doesn't pass it is unaffected (1.0 = "assume full coverage", the
    # same as omitting the concept entirely, which was the prior behavior).
    coverage:      float = 1.0

    def to_dict(self) -> dict:
        return {
            "rank":             self.rank,
            "symbol":           self.symbol,
            "composite_score":  self.composite_score,
            "breakdown":        self.breakdown.to_dict(),
            "explanation":      self.explanation,
            "ranked_at":        self.ranked_at,
            "data_age_s":       self.data_age_s,
            "coverage":         self.coverage,
        }
