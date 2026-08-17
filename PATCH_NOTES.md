# PATCH NOTES — Track B: Train Monitor Dashboard Tab

Branch: `feat/dashboard-train-monitor-tab`
Base: `main` @ `ece01c9` (rebased — `origin/main` advanced past this
branch's original `a88bb5b` base via PR #64 while this branch was in
flight; rebased cleanly onto current `main` with conflicts in
`CHANGELOG.md`, `MIGRATION.md`, `PATCH_NOTES.md` only — all three are
per-phase snapshot/append docs that both phases touched independently.
Resolved by stacking this phase's `CHANGELOG.md` entry above PR #64's
(both kept, newest first, same pattern already established there), and
keeping this phase's own `PATCH_NOTES.md`/`MIGRATION.md` content in
full — same convention every prior phase in this repo has used;
neither file is cumulative. No other file conflicted — PR #64 never
touched `pages/`, `lib/trainMonitor.ts`, `types/api.ts`, `App.tsx`, or
`components/layout/Layout.tsx`.)

## Scope note

Requested directly ("add a Train Monitor tab to check training results
and confirm the system is still training normally"). Track B
(`dashboard_src/`) only — zero Track A / `.py` files touched, zero new
backend routes. Everything this page shows was already served by
existing, already-implemented endpoints; two of the three data sources
were already being polled globally and simply never had anywhere to
be seen.

## What already existed (inspected before writing anything)

- `GET /api/ml/status`, `GET /api/ml/performance` — already implemented
  (`api/app.py`), already polled every 15s by `useMLData()`
  (`hooks/useData.ts`, called from `useAllData()`), already stored in
  the global `useML()` Zustand slice. `SystemHealth.tsx` already shows
  a compact summary panel from this same data.
- `GET /api/ml/models` — already implemented, already wired as
  `api.mlModels()` in `lib/api.ts` — but **not called from any page**.
  This is the model-version history (win rate / profit factor / max
  drawdown / training rows per version, per model type) — i.e. the
  actual "training results" half of the request, and it existed but
  was invisible.

Nothing here duplicates `SystemHealth.tsx`'s existing compact ML
panel; that stays untouched. This tab is the dedicated, full view:
per-model-type version history (previously nowhere in the UI),
current-active-model detail, and full last-prediction detail.

## What's new

- `dashboard_src/src/pages/TrainMonitor.tsx` — new page/tab:
  - Top row: ACTIVE/NONE per model type (meta_label, calibrator,
    outcome_predictor — from the already-live `useML().status`),
    dataset total/labelled row counts, and a session-local growth
    counter (see below).
  - "Model Training History" panel — tab-selectable per model type,
    table of every recorded training run (version, created, algorithm,
    rows, win rate, profit factor, max drawdown, active/retired,
    notes) — from `api.mlModels()`, polled locally every 20s (same
    page-local `useEffect`+`setInterval` pattern already used by
    `TradeReplay.tsx`/`DebateRoom.tsx`/`Memory.tsx`).
  - "Currently Active" panel — the active model's own metrics for
    whichever type is selected, from the already-live
    `useML().performance`.
  - "Last Prediction" panel — full detail (action, label, raw vs.
    calibrated confidence, outcome probability) with a live relative
    timestamp (`timeAgo()`, already existed in `components/common`).
- `dashboard_src/src/lib/trainMonitor.ts` — new, additive:
  `computeRowsGrowth(firstObserved, current)`, a small pure function
  for "dataset rows added since this tab was opened." Returns `null`
  until a baseline exists (distinct from a real `0`, which means "no
  growth yet" and must stay visible as such) — see its own tests.
- `dashboard_src/src/lib/tests/trainMonitor.test.ts` — 5 new cases.
- `dashboard_src/src/types/api.ts` — added `MLModelsData` (mirrors
  `GET /api/ml/models`'s actual response shape exactly). No existing
  type touched.
- `App.tsx` / `Layout.tsx` — new route (`/train`) and nav entry
  ("Train Monitor", short `TRN`), placed next to "AI Memory" in the
  sidebar. No existing route or nav entry changed.

## Why no invented "training is healthy" verdict

The system's own watchdog (`system_health.watchdog`) tracks
ALIVE/STALE/DEAD per subsystem using its own known heartbeat
intervals — `main_loop`, `monitor_loop`, `trade_manager`, etc. There
is no equivalent registered heartbeat for ML training, and this page
doesn't know the real cadence well enough to safely invent one (would
violate "never invent APIs/behavior that doesn't exist" — a wrong
threshold is worse than no threshold). Instead this page shows the
real, honest signals and lets the operator judge them: last-prediction
raw timestamp + relative age, and dataset-row growth **observed by
this page itself, over however long it's actually been open** — never
a guessed "stuck" verdict.

## Files changed

- `dashboard_src/src/pages/TrainMonitor.tsx` (new)
- `dashboard_src/src/lib/trainMonitor.ts` (new)
- `dashboard_src/src/lib/tests/trainMonitor.test.ts` (new, 5 cases)
- `dashboard_src/src/types/api.ts` (+4 lines, additive type)
- `dashboard_src/src/App.tsx` (+2 lines: lazy import + route)
- `dashboard_src/src/components/layout/Layout.tsx` (+1 line: nav entry)

## Tests executed

- `npx vitest run` — before: 6 files / 66 passed. After: **7 files /
  71 passed** (5 new, 0 modified, 0 removed).
- `npx tsc --noEmit` — clean before and after.
- `npm run build` (`tsc && vite build`) — clean, 444 modules
  transformed, new `TrainMonitor-*.js` chunk (~7.3 kB) code-splits
  correctly as its own lazy route, same as every other page.
- Re-verified after the rebase onto `ece01c9` (see Branch/Base above):
  `tsc --noEmit`, `vitest run` (71 passed), and `npm run build` all
  re-run clean against the new base, plus an independent second-clone
  bundle-import verification.
- Python quality gates not re-run: zero `.py` files in this diff;
  `ruff`/`vulture` already exclude `dashboard_src`.

## Known follow-up (not in this bundle)

`/ws/ml` (`api/app.py`) is documented as pushing ML advisor status
"at 2s intervals" but its handler only ever sends one `init` frame and
then blocks on `ws.receive_text()` — no periodic broadcast loop calls
it. This page (and `SystemHealth.tsx`) work around it correctly via
the 15s HTTP poll already in `useMLData()`, so nothing here is
functionally broken by it, but the docstring doesn't match the
implementation. Flagging, not fixing — unrelated to this phase and
outside Track B's own files (`api/app.py` is Track A).
