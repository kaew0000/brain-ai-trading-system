# ARCHITECTURE_REPORT

This is the merge-specific verification pass (Step 6 of the merge
brief). For the full living dependency graph, see `docs/architecture.md`
(already maintained inside the merge base and carried over unchanged).

## Method

AST-based import graph built by walking every `.py` file under the
repository root (excluding `dashboard`, `dashboard_src`, caches),
resolving `import x` / `from x import y` against the set of actual
local module paths, then running cycle detection (DFS) over the
resulting graph.

## Result

- **127 backend modules scanned.**
- **0 circular imports detected.**
- **No duplicated core service classes found**: exactly one `RiskEngine`
  (`risk/risk_engine.py`), exactly one `ExecutionCoordinator`
  (`execution/execution_coordinator.py`). No `PortfolioManager` class
  exists anywhere in the tree under that name — if you were expecting
  one (e.g. as a consumer of the new `scanner`/`ranking` output), it
  hasn't been built yet in any of the merged patches; I'm flagging this
  rather than inventing one, per the "never invent missing modules"
  rule.

## New modules introduced by this merge

- `scanner/` (V16 Phase 2 Part 1) — market-wide scanning, off by
  default (`SCANNER_ENABLED=False`)
- `ranking/` (V16 Phase 2 Part 2) — composite opportunity ranking on
  top of scanner output: `opportunity_ranker.py`, `confidence_fusion.py`,
  `score_breakdown.py`, `ranking_history.py`, `ranking_models.py`
- `docs/` — architecture/migration docs (distinct from the pre-existing
  `reports/` historical-audit folder, kept separately — see
  `MERGE_REPORT.md` §4)

`scanner/` is wired into `main.py` (started conditionally, gated behind
`SCANNER_ENABLED`, default `False`). `ranking/` is **not** referenced
anywhere outside its own module and tests — confirmed via the import
graph, nothing in `main.py`, `pipeline/`, or elsewhere imports from
`ranking/` yet. So the ranking engine currently only runs inside its
own test suite; nothing production wires its output anywhere. Both
modules are disabled/inert by default, so merging them introduces no
behavior change for existing deployments either way.

## Known gap

There's no `PortfolioManager` (or equivalent) consuming
`ranking/opportunity_ranker.py`'s output yet. If a "Portfolio modules"
patch was expected to exist per the original task brief but isn't in
`Brain_Bot_PATCH/`, it wasn't merged because it wasn't found in the
uploaded archive — not because it was skipped or judged unnecessary.
