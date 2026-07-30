"""
learning/dataset_builder.py — V16 Phase 4C Step 1: Autonomous Learning
Pipeline (Track A — see docs/architecture/SEPARATION_POLICY.md)

Wraps journal.journal_v2.TradeJournalV2.get_ensemble_learning_dataset()
(built in Phase 4B Step 2, docs/architecture.md §29) — this module does
NOT re-query the database or duplicate that join logic. "Do not
duplicate existing modules" (this phase's own constraint) means this
file's only real job is shaping journal rows into a typed,
analysis-ready LearningDataset and computing a small number of
genuinely-derived sequence statistics (cumulative PnL, running
drawdown) that no single trade row could carry on its own.

READ ONLY, same as every module in learning/: nothing here writes to
the journal, mutates a trade, or changes any Track A production
component's behavior. See learning/__init__.py's module docstring for
the package-wide constraint list.

Fields not yet populated in current storage
--------------------------------------------
Every LearningRow field below exists whether or not real data is
behind it yet — the schema is honest about the difference rather than
silently omitting requested-but-unavailable fields:

- `market_context`, `volatility`, `atr`, `spread` are always None
  today. No Track A write path persists a market-context/indicator
  snapshot at trade time (confirmed by reading journal/journal_v2.py's
  schema and every record_trade_outcome() call site) — adding that
  would mean changing execution/journal write behavior, which this
  phase's brief explicitly forbids. Flagged here and in this phase's
  "Future Phase Proposal" rather than fabricated.
- `regime`, `signal_confidence`, `score`, `mtf_aligned`, `smc_flags`
  are real for legacy single-symbol trades (journal/journal_v2.py's
  `trades` table has carried these since Phase 2A) but are None for
  V16 multi-symbol trades — execution/execution_orchestrator.py's
  `_record_trade_opened()` (Phase 4B Step 2) never threaded the
  computed market_context's regime/confidence into the TradeRecord it
  builds. A real, verified gap in an earlier phase, not introduced or
  fixed here (fixing it would mean touching ExecutionOrchestrator,
  also forbidden this phase).
- `agent_participation` is real for legacy trades and for CEO-gated
  multi-symbol trades' own CEO_AGENT-tagged decision row (Phase 4B
  Step 3C), but empty for any multi-symbol trade taken with
  CEO_MULTI_SYMBOL_ENABLED=false (the default) — see
  docs/architecture.md §29/§31's own "Scope boundary" sections.
- `reason`/`source`/`duration_seconds`/`close_confidence` are real for
  any trade closed through execution/trade_lifecycle.py's
  TradeLifecycle (Phase 4B Step 3D) — None for anything closed before
  that phase existed, or through a path that still bypasses it.

cumulative_pnl / running_drawdown ARE genuinely computed here (not raw
storage) — a simple running sum and running peak-to-trough over the
dataset's rows in chronological order. This is real, derived analysis,
clearly distinguished in the dataclass from the raw-or-unavailable
fields above it.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from utils.logger import get_logger

logger = get_logger(__name__)

DATASET_SCHEMA_VERSION = "4c-step1.0"


@dataclass(frozen=True)
class LearningRow:
    """One closed trade, shaped for learning/analysis. See this
    module's docstring for exactly which fields are real in today's
    storage vs. schema-ready-but-not-yet-populated."""

    # identity / journal references
    trade_id:            int
    symbol:              str
    timestamp:           str
    journal_references:  dict  # {"trade_id":, "order_id":, "execution_id":}

    # trade facts
    direction:           str | None
    entry_price:         float | None
    exit_price:           float | None
    quantity:            float | None
    stop_loss:           float | None
    take_profit:          float | None
    result:              str | None
    pnl:                 float | None
    rr:                  float | None
    duration_seconds:    float | None
    reason:              str | None   # execution.trade_lifecycle.CloseSource value, if recorded
    source:              str | None

    # market context available today (legacy single-symbol trades only — see module docstring)
    regime:              str | None
    mtf_aligned:         bool | None
    smc_flags:           dict

    # confidence / ensemble
    signal_confidence:   float | None
    close_confidence:    float | None
    score:               float | None
    agent_participation:  list
    ceo_decision:         dict | None
    ensemble_weights:     dict

    # execution facts
    fees:                float | None
    slippage:             float | None
    latency_seconds:      float | None

    # NOT populated by any current Track A write path — see module
    # docstring "Fields not yet populated". Present for schema
    # completeness / forward compatibility, always None today.
    market_context:       dict | None = None
    volatility:           float | None = None
    atr:                  float | None = None
    spread:               float | None = None

    # genuinely derived by this builder (not raw storage) — see module docstring
    cumulative_pnl:       float | None = None
    running_drawdown:     float | None = None
    sequence_index:       int | None = None


@dataclass(frozen=True)
class LearningDataset:
    rows:              tuple           # tuple[LearningRow, ...] — tuple, not list, for real immutability
    generated_at:       str
    schema_version:      str
    source_params:       dict           # {"limit":, "symbol":}
    row_count:           int

    def __len__(self) -> int:
        return self.row_count

    def to_dicts(self) -> list[dict]:
        """Flat list[dict] view — what learning_report.py/JSON snapshots
        actually serialize, since LearningRow itself isn't JSON-safe by
        default (nested dataclass)."""
        from dataclasses import asdict
        return [asdict(r) for r in self.rows]


def _row_to_learning_row(raw: dict, sequence_index: int, cumulative_pnl: float, running_drawdown: float) -> LearningRow:
    participation = raw.get("agent_participation") or []
    ceo_decision = next((a for a in participation if a.get("agent") == "ceo"), None)
    ensemble_weights = {a["agent"]: a.get("weight") for a in participation if a.get("agent") != "ceo"}

    return LearningRow(
        trade_id=raw["trade_id"],
        symbol=raw.get("symbol"),
        timestamp=raw.get("timestamp"),
        journal_references={
            "trade_id": raw["trade_id"],
            "order_id": raw.get("order_id"),
            "execution_id": raw.get("execution_id"),
        },
        direction=raw.get("direction"),
        entry_price=raw.get("entry_price"),
        exit_price=raw.get("exit_price"),
        quantity=raw.get("quantity"),
        stop_loss=raw.get("stop_loss"),
        take_profit=raw.get("take_profit"),
        result=raw.get("result"),
        pnl=raw.get("pnl"),
        rr=raw.get("rr"),
        duration_seconds=raw.get("duration_seconds"),
        reason=raw.get("reason"),
        source=raw.get("source"),
        regime=raw.get("regime"),
        mtf_aligned=raw.get("mtf_aligned"),
        smc_flags=raw.get("smc_flags") or {},
        signal_confidence=raw.get("signal_confidence"),
        close_confidence=raw.get("close_confidence"),
        score=raw.get("score"),
        agent_participation=participation,
        ceo_decision=ceo_decision,
        ensemble_weights=ensemble_weights,
        fees=raw.get("fees"),
        slippage=raw.get("slippage"),
        latency_seconds=raw.get("latency_seconds"),
        cumulative_pnl=cumulative_pnl,
        running_drawdown=running_drawdown,
        sequence_index=sequence_index,
    )


class LearningDatasetBuilder:
    """Constructed with anything exposing
    get_ensemble_learning_dataset(limit=, symbol=) -> list[dict] — in
    production a journal.journal_v2.TradeJournalV2 instance, but this
    class only calls that one method, so a test fake needs nothing
    else (same duck-typing convention as
    journal/trade_attribution.py's record_trade_outcome())."""

    def __init__(self, journal) -> None:
        self.journal = journal

    def build(self, limit: int = 10_000, symbol: str | None = None) -> LearningDataset:
        """Never raises: a journal read failure is logged and produces
        an empty (not partial/corrupt) LearningDataset — learning must
        never be able to look like a crash to anything that calls it,
        matching this project's "diagnostic data must never break
        anything" rule used throughout journal/trade_attribution.py."""
        try:
            raw_rows = self.journal.get_ensemble_learning_dataset(limit=limit, symbol=symbol)
        except Exception as exc:
            logger.error(f"LearningDatasetBuilder: journal read failed: {exc}")
            raw_rows = []

        # Chronological order for a meaningful cumulative/drawdown
        # series — get_ensemble_learning_dataset() itself returns most-
        # recent-first (ORDER BY timestamp DESC), so reverse it here
        # rather than assuming the caller already sorted it.
        raw_rows = sorted(raw_rows, key=lambda r: r.get("timestamp") or "")

        rows: list[LearningRow] = []
        cumulative = 0.0
        peak = 0.0
        for i, raw in enumerate(raw_rows):
            pnl = raw.get("pnl")
            if pnl is not None:
                cumulative += pnl
            peak = max(peak, cumulative)
            drawdown = cumulative - peak  # <= 0
            rows.append(_row_to_learning_row(raw, sequence_index=i, cumulative_pnl=round(cumulative, 4),
                                              running_drawdown=round(drawdown, 4)))

        return LearningDataset(
            rows=tuple(rows),
            generated_at=datetime.now(timezone.utc).isoformat(),
            schema_version=DATASET_SCHEMA_VERSION,
            source_params={"limit": limit, "symbol": symbol},
            row_count=len(rows),
        )
