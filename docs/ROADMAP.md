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
✅ Per-agent vote persistence / attribution for CEO-gated multi-symbol
  trades — already shipped and wrongly left under "Planned": per-agent
  `agent_decisions` rows with a shared `signal_id` (Phase 4C Step 7 / 7C,
  PRs #48/#51, §35) plus explicit `trades.extra_data` attribution
  (W14-2A, PR #54, §37) feed `get_ensemble_learning_dataset()`, the `learning/`
  package and `get_agent_performance()`. Reproduced end to end against
  `main` @ `98088ca`; §76 documents it and locks the open → close →
  dataset flow with `tests/test_ceo_vote_persistence_lifecycle.py` (no
  code change, no backfill needed — no data is missing).
✅ `get_ensemble_learning_dataset()` N+1 read pattern — already fixed at
  V16 §63 (commit `a702c27`, 2026-09-12: one trades query + one
  `agent_decisions` query regardless of `limit`) and wrongly left under
  "Planned" afterwards. Re-measured on `main` @ `ec67c57`: constant SQL
  statement count, 5,000 trades in ~0.3 s. This PR (§77) documents that
  verified baseline and adds `tools/benchmark_ensemble_dataset.py` so a
  future regression is measurable; no code behavior change.
✅ Agent-key namespace vs dynamic weighting (§76's P1) — `CEOAgent._effective_weights()` looked agents
  up by display name (`"SMC_ANALYST"`) while CEO-gated trades persist under the `CEOAgent.WEIGHTS` key
  (`"smc"`), so dynamic weighting never saw CEO-gated performance. Fixed in §78 with a read-side alias table
  (`journal/trade_attribution.py::WEIGHTS_KEY_ALIASES`) merged at the lookup boundary — no renames, no
  change to stored rows or to `get_agent_performance()`. Merged via branch `fix/weighting-key-namespace`
  (PR number to be added at merge). **`DYNAMIC_AGENT_WEIGHTS_ENABLED` is still off by default, pending a
  human enable** — nothing in §78 turns it on.

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

- Fee capture (no write path fetches Binance commission data today).
- Training lane -> learning loop (found in §86 audit): `ml/confidence_calibrator.train_calibrator()` still has no production caller;
  `run_nightly_retrain()` runs once a day at 02:00 only, so a bust/reset cycle of the always-on training lane does not trigger a retrain.
  Must stay behind the human-approved promotion gate.
- `main.py` printed daily report mixes all execution lanes (training trades appear as "Today trades"); scope to LIVE or label per lane.
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
- **P2 — learning-dataset cohorts: decide how to treat trades without
  explicit attribution.** CEO-gated trades fall into three cohorts, all
  visible in `get_ensemble_learning_dataset()`: (a) before Step 7C
  (2026-08-10) or taken without CEO gating — empty `agent_participation`;
  (b) Step 7C up to W14-2A (2026-08-14) — participation derived from the
  `agent_decisions` join, which names the CEO `"CEO_AGENT"`, includes
  `trader` (weight 0.0, never a vote) and uses `contribution =
  round(score * weight, 2)`; (c) after W14-2A — explicit attribution, CEO
  named `"ceo"`, WEIGHTS agents only. Evaluate whether the dataset should
  mark (a) as unattributable and/or exclude (a)/(b) from agent statistics,
  and whether `"CEO_AGENT"` and `"ceo"` should be unified in
  `learning/agent_statistics.py` (today they are separate buckets). The
  cohort boundaries are derived from code and the §35/§37 dates, not
  measured on a production journal. Until decided: leave as is (§76
  documents the cohorts; nothing is rewritten or backfilled).
- **Needs decision — live-readiness: daily-loss gate day boundary (local date vs UTC timestamps).**
  `journal_v2.get_daily_stats()` defaults `day` to `date.today()` (the process's LOCAL date) but queries
  `date(timestamp)` over timestamps that callers store in UTC. `RiskEngine.check_daily_loss()` reaches it via
  `get_today_pnl(execution_lane="LIVE")`. Verified: `tests/test_journal_v2_risk_gate_lane_scoping.py::
  test_today_pnl_live_filter_ignores_training_lane_swings` passes under `TZ=UTC` and fails under
  `TZ=Asia/Bangkok` whenever the local date differs from the UTC date (00:00–07:00 Bangkok). Not verified:
  the timezone of the live host, or `RiskEngine` end to end — by reading the code, a host in a non-UTC zone
  would not count trades closed in that window towards "today". Needs a decision (use a UTC day boundary,
  or a documented host-TZ requirement) and a test pinned to a non-UTC `TZ`; also makes the suite
  time-of-day dependent for a developer in UTC+7. Found while baselining §78; not touched there.
