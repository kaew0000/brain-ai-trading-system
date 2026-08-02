# Brain Bot V16 Development Roadmap (Track A — Trading Engine)

> **Stabilization note (2026-08-02):** This file was last updated at the
> repository's very first commit (`07fdcac`, 2026-07-18) and had not
> tracked any of the ~20 phases merged since. Rewritten during the
> Repository Stabilization phase to match verified git history — see
> `docs/REPOSITORY_STABILIZATION_REPORT.md` for the full audit this
> rewrite is based on. Track B (Command World) has its own roadmap at
> `world/docs/roadmap.md`, per `docs/architecture/SEPARATION_POLICY.md`.

## Completed

Pre-repository-history (documented retrospectively in
`docs/architecture.md` §3–§15; dated 2026-07-15 to 07-17, before this
repo's first commit — no individual commit evidence exists for these
in this repository, see stabilization report):

✅ Fix #1 Risk Consolidation
✅ Fix #2 Watchdog Supervisor
✅ Fix #3 Circuit Breaker
✅ Dashboard Authentication (P1-A)
✅ Dynamic Risk Engine V2 (P1-B1)
✅ Multi Symbol Foundation
✅ Market Scanner
✅ Opportunity Ranker

V16.5.0 baseline through Phase 4C Step 1 (each has a merged commit,
PR, and `docs/architecture.md` section — see that file and
`CHANGELOG.md` for full detail on each):

✅ V16.5.0 GitHub-Ready baseline (`07fdcac`)
✅ Phase 2A — Portfolio Intelligence Core (architecture.md §17)
✅ Phase 2B — Portfolio Manager Orchestrator (§18)
✅ Phase 2C — Portfolio API (§19)
✅ Bundle Manager (`tools/`) (§21)
✅ Phase 2E — Execution Wiring & Live Orchestrator (§23)
✅ Phase 2F — Execution Scheduler + Multi-Symbol Signals (§24)
✅ Phase 3A — Strategy Plugin System (§25)
✅ Phase 4A — Ensemble Decision Engine: ConfidenceEngine Fusion (§26)
✅ Phase 4B Step 1 — Per-Agent Outcome Attribution (§27)
✅ Phase 4B proper — Dynamic Per-Agent Weighting (§28)
✅ Phase 4B Step 2 — Execution Attribution + Portfolio Integration (§29)
✅ Phase 4B Step 3A — Symbol Isolation (documented in §30's
  "Background"; see also the retrospective section added by the
  Stabilization phase)
✅ Phase 4B Step 3B — CEO Decision Context + Multi-Symbol Signal
  Integration (§30)
✅ Phase 4B Step 3C — Live CEO Agent Integration into Multi-Symbol
  Pipeline (§31)
✅ Phase 4B Step 3D — Unified Trade Lifecycle & Trade Attribution
  (§32, tagged `v16-engine-phase4b-step3d`)
✅ Phase 4C Step 1 — Autonomous Learning Pipeline (§33, Track A;
  `learning/` package, read-only)

**Note on numbering:** the sequence 2A → 2B → 2C → 2E → 2F has no
"Phase 2D" anywhere in commit messages, `CHANGELOG.md`,
`docs/architecture.md`, or `CLAUDE.md`. Not verifiable from repository
evidence whether this was intentional or a genuine gap — see the
stabilization report.

## In Progress

Nothing is currently in progress as of this rewrite — the items below
are scoped, documented as open, and not yet started.

## Planned

Precisely scoped in `docs/architecture.md` §29/§30/§31/§32/§33's own
"Next up" sections and `CLAUDE.md`'s "Current Priorities" — summarized
here, not re-derived:

- Natural SL/TP close monitor for the V16 multi-symbol path (today
  only replacement-triggered closes are wired to attribution).
- Pass `symbol=` to `RegimeEngine.classify()` from
  `PortfolioSignalProvider` — closes a still-live cross-symbol HMM
  contamination gap.
- Per-agent attribution for CEO-gated multi-symbol trades (agent votes
  still aren't persisted for that path).
- Fee capture (no write path fetches Binance commission data today).
- Fix `get_ensemble_learning_dataset()`'s N+1 read pattern — doesn't
  scale past ~1,000 trades (measured in Phase 4C Step 1's benchmark).
- Multi-Agent Framework enhancements (extend `agents/` + `graph/` +
  `commander/`).
- Quant Research Pipeline / Research-Optimization Framework (extend
  `research/` + `ml/`).
- AI Self-Improvement, human-approved only (gate on top of
  `ml/learning_mode.py`'s existing auto-promotion logic).
- Correlation Engine / Sector Engine (real correlation tracking,
  sector-cap capital redistribution).
- Portfolio Dashboard (execution + scheduler panel).
- Phase 4C Step 2+ — actually consuming the Learning Pipeline's
  dataset for something beyond observation (explicitly deferred by
  Phase 4C Step 1's own "observation and recommendation only" brief).
