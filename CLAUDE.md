# Brain Bot V16

This repository is the canonical source of Brain Bot V16 Autonomous AI Trading Platform.

---

# Project Mission

Build a production-grade autonomous AI trading platform capable of:

- Multi-symbol trading
- AI-assisted decision making
- Dynamic risk management
- Portfolio optimization
- Autonomous monitoring
- Continuous self-improvement

Reliability and capital preservation are always higher priority than trading frequency.

---

# Current Development Status

Completed

- Fix #1 Risk Consolidation
- Fix #2 Watchdog Supervisor
- Dashboard Authentication
- Dynamic Risk Engine V2
- Multi Symbol Foundation
- Market Scanner
- Opportunity Ranker
- Portfolio Manager (Intelligence Core + Orchestrator + API — see architecture.md §17-19)
- Bundle Manager
- Execution Wiring & Live Orchestrator
- Execution Scheduler + Multi-Symbol Signals
- Strategy Plugin System (architecture.md §25 — `execution/strategy_registry.py`)
- Ensemble Decision Engine Phase 4A — ConfidenceEngine fusion + agreement
  scoring (architecture.md §26 — `agents/ceo_agent.py`)
- Ensemble Decision Engine Phase 4B Step 1 — per-agent outcome attribution
  (architecture.md §27 — `journal/journal_v2.py` + `main.py`)
- Ensemble Decision Engine Phase 4B proper — dynamic per-agent weighting
  (architecture.md §28 — `agents/ceo_agent.py`, off by default via
  `DYNAMIC_AGENT_WEIGHTS_ENABLED`)
- Ensemble Decision Engine Phase 4B Step 2 — execution attribution +
  portfolio integration (architecture.md §29 — `journal/trade_attribution.py`,
  `execution/execution_orchestrator.py`, `portfolio/portfolio_manager.py`)
- Ensemble Decision Engine Phase 4B Step 3A — symbol isolation prep
  (`AgentReport.symbol`, `CEODecision.symbol`, `RegimeEngine` per-symbol
  HMM models — merged, not separately documented in architecture.md by
  that PR; see §30's "Background" for the record)
- Ensemble Decision Engine Phase 4B Step 3B — CEO decision context +
  multi-symbol signal integration (architecture.md §30 —
  `agents/decision_context.py`, `agents/multi_symbol_adapter.py`,
  `execution/portfolio_signal_provider.py`'s `get_signal_with_context()`,
  `CEOAgent.decide_from_context()`)
- Ensemble Decision Engine Phase 4B Step 3C — live CEO Agent
  integration into the multi-symbol decision pipeline (architecture.md
  §31 — `execution/ceo_gated_signal_provider.py`,
  `agents/ceo_symbol_cache.py`, `CEO_MULTI_SYMBOL_ENABLED` off by
  default; merged, not documented in this file by that PR — backfilled
  here)
- Ensemble Decision Engine Phase 4B Step 3D — unified trade lifecycle &
  trade attribution (architecture.md §32 —
  `execution/trade_lifecycle.py`'s `TradeLifecycle`, the single write
  path for every close reason: SL/TP, replacement, reconciliation,
  emergency close, exchange reject; merged, not documented in this file
  by that PR — backfilled here)
- Autonomous Learning Pipeline — Phase 4C Step 1 (architecture.md §33 —
  new `learning/` package, Track A, READ ONLY: dataset builder,
  symbol/regime/agent/feature statistics, performance tracker, pattern
  miner, recommendation engine, immutable snapshots, JSON reports)
- RL/HPO/Online-Learning Extensions Subpackage (architecture.md §52 —
  `ml/extensions/`: Stable-Baselines3 RL, River online learning, Optuna
  HPO, behind an `ExtensionsOrchestrator`; optional deps only, nothing
  else in the repo imports it; merged as PR #82, not documented in this
  file or architecture.md by that PR — backfilled here)
- ML Extensions Integration Layer — observe-only (architecture.md §53 —
  `ml/extensions_integration/`: real data/portfolio adapters + an
  `MLExtensionsAgent` registered with `CEOAgent` under a key deliberately
  outside `CEOAgent.WEIGHTS`, so it has zero effect on any real trading
  decision this phase; `ML_EXTENSIONS_ENABLED`, off by default; a
  read-only `/api/ml_extensions/*` monitoring API)

In Progress

- (none — see Current Priorities below for the next scoped phase)

Planned — re-scoped 2026-07-23 around a production AI trading platform
direction (each pillar below is its own future phase, scoped against
existing code before implementation — see architecture.md §25 "Next up"
for what already exists under each pillar):

- Ensemble Decision Engine (extends `agents/ceo_agent.py` + `decision/`
  + `ranking/confidence_fusion.py` — already substantially exists)
- Multi-Agent Framework enhancements (extends `agents/` +
  `graph/agent_graph.py` + `commander/` — already substantially exists;
  NOT the Anthropic MCP protocol unless later specified otherwise)
- Quant Research Pipeline (extends `research/`)
- Research/Optimization Framework (extends `ml/trainer.py` +
  `ml/model_registry.py` — needs a scoping pass to separate from the
  pillar above)
- AI Self-Improvement, human-approved only (adds an approval gate on
  top of `ml/learning_mode.py`'s existing auto-promotion logic)
- Correlation Engine / Sector Engine (real correlation tracking,
  sector-cap capital redistribution — carried forward from earlier
  phases, still open)
- Portfolio Dashboard (execution + scheduler panel — carried forward,
  still open)

---

# Architecture

Core Pipeline

Scanner

↓

Ranking Engine

↓

Portfolio Manager

↓

Risk Engine

↓

Decision Engine

↓

Execution Layer

↓

Trade Journal

↓

Dashboard

Never bypass this pipeline.

---

# Engineering Principles

Always preserve backwards compatibility.

Never rewrite completed modules.

Prefer additive changes.

Inspect existing implementation before modifying.

Never invent APIs.

Never invent class names.

Never invent method signatures.

Always inspect architecture.md before coding.

Always update architecture.md after major changes.

Always update CHANGELOG.md.

Always run tests before delivery.

Never remove tests.

Never decrease test coverage.

Never commit secrets.

Never commit databases.

Never modify RiskEngine without full inspection.

Never modify Execution Layer blindly.

Always explain architectural conflicts before implementation.

---

# Coding Workflow

Before coding

1. Read architecture.md

2. Read CLAUDE_RULES.md

3. Read ROADMAP.md

4. Inspect imports

5. Search existing implementation

6. Explain proposed design

7. Wait if architecture conflict exists

After coding

Run Ruff

Run Pytest

Update Docs

Produce unified diff

Summarize changes

---

# Current Priorities

(Portfolio Manager, Capital Allocation, and Execution Scheduler are
done — see Completed above. Priorities below re-scoped 2026-07-23.)

Priority 1

Strategy Plugin System — DONE (architecture.md §25)

Priority 2

Ensemble Decision Engine — Phase 4A through Phase 4B Step 3D all DONE
(architecture.md §26-§32). Phase 4B Step 3C put CEOAgent live on the
multi-symbol path behind `CEO_MULTI_SYMBOL_ENABLED` (off by default).
Phase 4B Step 3D unified every close path (SL/TP, replacement,
reconciliation, emergency, exchange-reject) through one
`TradeLifecycle` write path. What's still open, scoped precisely in
§32/§33 "Next up" rather than re-described here: 1) per-agent
attribution for CEO-confirmed multi-symbol trades (still not wired —
`agent_attribution_from_ceo_decision()` still isn't called anywhere),
2) passing `symbol=` to `RegimeEngine.classify()` from
`PortfolioSignalProvider` (cross-symbol HMM contamination still live),
3) per-symbol sub-agent instance state, 4) fee capture,
5) `get_ensemble_learning_dataset()`'s N+1 read pattern doesn't scale
past ~1,000 trades (found while building Phase 4C Step 1's benchmark —
architecture.md §33).

Phase 4C Step 1 DONE (architecture.md §33): new `learning/` package —
Autonomous Learning Pipeline, Track A, READ ONLY (observation +
recommendation only, no automatic weight/parameter/strategy changes).
Wraps the existing `get_ensemble_learning_dataset()` (§29); does not
duplicate it. See §33 for the full pipeline diagram and Future Phase
Proposal.

Priority 3

Multi-Agent Framework enhancements (extend `agents/` + `graph/` + `commander/`)

Priority 4

Quant Research Pipeline / Research-Optimization Framework (extend `research/` + `ml/`).
Phase 4C Step 1's `learning/` package (Priority 2, architecture.md §33)
covers the "Ensemble Learning" slice of this pillar specifically —
research/ml-wide research infrastructure is still untouched.

Priority 5

AI Self-Improvement, human-approved only (gate on top of `ml/learning_mode.py`)

Priority 6

Correlation Engine / Sector Engine

Priority 7

Portfolio Dashboard

---

# Do NOT

Do not rewrite the whole project.

Do not delete working code.

Do not duplicate managers.

Do not hardcode secrets.

Do not reduce modularity.

Do not break public interfaces.

Do not silently change business logic.

Do not disable tests.

Do not ignore failed tests.

---

# Success Criteria

Every feature must be:

Backward compatible

Tested

Documented

Modular

Reviewable

Production ready
