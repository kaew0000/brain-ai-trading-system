# CHANGELOG

## [Unreleased] — Bundle Manager (tools/)

### Added
- New `tools/` package: `git_utils.py`, `bundle_utils.py`, `history.py`,
  `github_actions.py`, `sync.py`, `ui.py`, `bundle_manager.py` (CLI).
  Automates importing `.bundle`/`.bundle.txt` files dropped into
  `update/incoming/`: verify → extract feature branch/SHA → skip
  duplicates (`bundle_history.json`) → fetch → checkout → push → file
  into `update/applied/` or `update/failed/`. `sync` fast-forwards the
  base branch after a merge. See `docs/architecture.md` §17.
- New `PORTFOLIO_*`-style `BUNDLE_*` settings in `config/settings.py`
  (`BUNDLE_INCOMING_DIR`, `BUNDLE_APPLIED_DIR`, `BUNDLE_FAILED_DIR`,
  `BUNDLE_HISTORY_FILE`, `BUNDLE_REMOTE`, `BUNDLE_BASE_BRANCH`,
  `BUNDLE_PUSH_RETRIES`, `BUNDLE_GIT_TIMEOUT_SECONDS`).
- `update/{incoming,applied,failed}/` directories (tracked via
  `.gitkeep`; contents gitignored).
- 98 new tests (`tests/test_bundle_manager_*.py`). Full suite:
  1001 → 1099 passed, 0 failed.

### Design notes
- Dry-run preview + confirmation before any real fetch/checkout/push;
  never force-pushes/force-fetches without `--force` (and then via
  `--force-with-lease`, never a bare `--force`).
- `bundle_history.json` is tracked in git (shared duplicate-import
  ledger), atomic writes.
- No `.github/workflows/*.yml` generated — out of scope, needs its own
  secrets/permissions design.

---

## [V16.5] — Patch consolidation merge (this repository)

Merged ten development-phase bundles into one tree. See
`MERGE_REPORT.md` for full detail. Summary of functional changes
relative to the pre-merge `Brain_Bot_RUN` baseline:

### Added
- **Dashboard API authentication** (P1-A): bearer-token auth
  (`api/auth.py`), `API_AUTH_ENABLED` / `API_KEYS` / `JWT_SECRET`
  settings, off by default.
- **Dynamic, volatility-aware risk sizing** (P1-B1): risk-per-trade and
  leverage calculation moved from `agents/risk_manager.py` into
  `risk/risk_engine.py` (`get_leverage`, `_volatility_factor`), now
  reacting to ATR-normalized volatility, not just consecutive-loss
  streaks.
- **Multi-symbol foundation** (P1-C): `Settings.symbol_list` /
  `SYMBOLS` env var — architecture-only, falls back to the existing
  single-`SYMBOL` behavior when unset, so no deployment is affected
  unless explicitly opted in.
- **Market Scanner** (V16 Phase 2 Part 1): `scanner/market_scanner.py`,
  wired into `main.py`, gated behind `SCANNER_ENABLED` (default off).
  New `scanner_snapshots` table.
- **Opportunity Ranking Engine** (V16 Phase 2 Part 2): `ranking/`
  package (composite scoring across trend/momentum/volume/funding/
  liquidity/risk/AI-confidence/historical-performance factors). New
  `ranking_history` table. Not yet wired to a consumer — see
  `ARCHITECTURE_REPORT.md`.
- **Watchdog supervision**: `system_health/watchdog.py` gains
  `WatchdogSupervisor`, paired with `systemd`'s `Type=notify` +
  `WatchdogSec=30` in `deployment/systemd/brain_bot.service`.
- Duplicate-order-id protection in `execution/trade_manager.py`
  (`_is_duplicate_order_error`, `new_client_order_id`).
- `PyJWT` added to `requirements.txt` (dashboard auth dependency).

### Fixed
- `/paper_trades` API endpoint returns `200` with `enabled: false`
  instead of `503` when the paper engine isn't running, so the
  dashboard renders a clean empty state instead of an error
  (previously shipped as a loose, unapplied `.patch` file — now
  confirmed applied and the stray patch file removed).

### Changed
- `agents/risk_manager.py`: risk-percentage calculation delegated to
  `RiskEngine` rather than computed locally (see Added, dynamic risk).

### Repository hygiene
- Removed dead patch artifacts (`findstr`, `uvicorn.txt`,
  `paper_metrics_503_fix.patch`, a stray brace-expansion-named empty
  directory) — see `CLEANUP_REPORT.md`.
- Added `.github/workflows/ci.yml` (lint + test + advisory
  `pip-audit`) and `release.yml`.
- Added `CONTRIBUTING.md`, `SECURITY.md`, `LICENSE`.

---

Earlier history is described in `docs/V16_AUDIT_REPORT.md`,
`docs/V16_PHASE1_MULTISYMBOL_MIGRATION.md`, and `reports/` (V14/V15-era
audits), carried over unchanged by this merge.
