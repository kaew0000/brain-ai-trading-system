"""governance/lane_breakdown.py — training-row composition by execution_lane.

Small, standalone helper: given a list of feature_rows-style dicts (as
research/feature_store.py::FeatureStore.get_training_rows() returns — each
row already carries its own `execution_lane` column, see that method's
SELECT * query), count how many came from each lane.

Exists because get_training_rows() has NO lane filter at all today (checked
before writing this) — every nightly retrain currently mixes LIVE,
TRAINING (the Track C background paper-training lane —
BACKGROUND_PAPER_TRAINING_ENABLED now defaults True, per the
feat/training-lane-visibility-and-boot-default PR), and PAPER rows with no
visibility into the mix. This function doesn't change that retrain
behaviour — that's Phase 2's job in ml/learning_mode.py — it only makes the
mix visible to whatever wants to report it, e.g.
agents/update_review_agent.py's model_promotion reasoning.
"""
from __future__ import annotations


def compute_lane_breakdown(rows: list[dict]) -> dict[str, int]:
    """Returns e.g. {"LIVE": 800, "TRAINING": 400}. Only lanes actually
    present in `rows` are included — never fabricates a zero count for a
    lane that simply didn't appear."""
    counts: dict[str, int] = {}
    for row in rows:
        lane = row.get("execution_lane") or "UNKNOWN"
        counts[lane] = counts.get(lane, 0) + 1
    return counts
