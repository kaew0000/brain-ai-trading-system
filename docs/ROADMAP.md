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
✅ Regime per-symbol HMM isolation — the `symbol=` call-site wiring
  landed in Phase 4B Step 3C (§31); the remaining failure-path gap (one
  symbol's HMM fit failure disabled HMM for all symbols) is closed in
  §74. This item was listed under "Planned" in error after §31 merged.
✅ Natural SL/TP close attribution for the V16 multi-symbol path — the
  journal/lifecycle attribution was wired in §60 + §32 (this item was
  listed under "Planned" in error); the remaining real gap — a naturally
  closed position was never released from the scheduler's PortfolioState,
  leaking a `max_positions` slot per close — is closed in §75.

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
- **Needs decision — natural-close fidelity (data feeding the learning
  pipeline):** a natural close is journaled with the poll-time mark price
  (up to ~30 s after the exchange filled the SL/TP order), not the real
  fill, and its cause is a WIN→TAKE_PROFIT / LOSS→STOP_LOSS heuristic
  (`reason="..._threshold_heuristic"`), so a trailing/breakeven stop that
  closes in profit reads as TP. The same heuristic serves the
  single-symbol path. Fixing it needs an exchange fill/order-history
  lookup that no data-provider method wraps today, plus testnet
  validation. A grep of `analytics/`, `learning/`, `ml/` and `journal/`
  found no consumer of the `SL`/`TP` close-source values, which lowers
  migration risk. See §75 "Not changed here".
- **Needs decision — paper mode with `SCHEDULER_ENABLED`:**
  `monitor_open_trades()` has no lane filter, so every PAPER-lane journal
  row is treated as "closed on the exchange" on the first poll (paper
  trades never exist on the real exchange). Pre-existing; unchanged by
  §75. Needs a lane-aware monitor (or an explicit unsupported-config
  guard).
- **Hardening:** a PortfolioState position whose journal save failed at
  open (`trade_id=None`) is invisible to the journal-driven monitor, so
  it is never released. Needs a state-driven reconciliation pass (read
  the PortfolioState snapshot BEFORE fetching exchange positions, so a
  just-filled position can't be mistaken for a closed one).
- **Hygiene, severity low, P2:** `tests/test_phase3_complete.py` writes
  `meta_label_*.pkl` into the live `ml_models/` registry directory.
  Tests should write to a temp `models_dir`. (Not a live risk —
  `ModelRegistry.load_active()` reads only the DB row with `active=1`,
  never scans the directory.)
- **Needs decision — touches live signal path:** `RegimeEngine`'s
  single shared `StandardScaler` is `fit_transform`-ed on every
  `classify()` call. The per-symbol HMM is fit once, on the first
  window's scaling, but scored on every later window re-scaled with that
  window's own mean/std — a scoring-consistency question. The shared
  scaler instance is also mutated on every call and is not thread-safe.
  Not an inter-symbol leak today (refit each call), but any fix (per-
  symbol scaler persisted with its HMM, or a fixed scaling) changes live
  regime output and needs an explicit decision plus before/after
  evidence. See §74 "Not changed here".
- **Enhancement — propose refit interval + evaluation before
  implementing:** each symbol's HMM is fit once (first `classify()` call
  per symbol) and never refit, so it goes stale as that symbol's
  volatility structure drifts. Needs a proposed refit interval and an
  offline evaluation (regime stability / agreement with the rule-based
  classifier, fit cost vs. latency budget) before any code. See §74.
