# PATCH NOTES — Auto-rebuild stale dashboard (V16 §84)

Branch: `fix/dashboard-stale-build-rebuild`
Base: `main` @ `6558457` (PR #122 merged)
Commit: `feat(launchers): auto-rebuild stale V16 dashboard (V16 §84)` (exactly one)

## Root cause (verified)
Symptom: `http://localhost:8000/world` "unusable" — empty World canvas, every `GET /api/world/rooms` answering 401, and none of the
§83 Studio tab present.
1. `dashboard_src/dist/` is git-ignored and is served as-is by `api/app.py` (`_DASHBOARD_SRC_DIST`).
2. `scripts/ensure_dashboard.bat` (PR #116) built it **only when `dist/index.html` was missing**. After `git pull` an old build
   (here: `index.html` from 24 Oct, bundle `WorldPage-BZFlg65m.js`, repo HEAD from 26 Oct) was served indefinitely, so §82/§83
   dashboard code never reached the browser and the World page's one-shot hydration failed.
3. Rebuilding from the same sources (`npm ci && npm run build`) produced `WorldPage-Hj4FlUkZ.js` and the World page worked
   (Studio tab, live data, non-empty canvas). No application source change was needed.
4. Separate, not caused by this: 401s on every `/api/*` call also occur whenever the browser session is not logged in.

## Changes (additive)
- `scripts/dashboard_build_state.py` (new): stdlib-only, read-only helper. Prints `fresh` | `build` | `install_build` (or `error`)
  by comparing build-input mtimes (`src/`, `public/`, `index.html`, `package*.json`, vite/ts/tailwind/postcss configs; test files,
  `tests/`, `node_modules` ignored) with `dist/index.html`. Always exits 0.
- `scripts/ensure_dashboard.bat` (changed): uses the helper. Missing `dist` -> `npm ci` + build (unchanged behaviour). Stale
  sources -> `npm run build`; changed `package*.json` or no `node_modules` -> `npm ci` first. The previous `dist` is copied to
  `%TEMP%\brain_dashboard_dist_backup` and restored if a rebuild leaves no `index.html`, so a failed rebuild cannot drop the
  operator onto the fake-data V13 demo. Still non-fatal for every launcher. If the helper cannot run, falls back to the old
  "build only if missing" behaviour.
- `tests/test_dashboard_build_state.py` (new): 23 tests (state matrix, CLI, read-only, static checks of the .bat contract and that
  all four launchers still call it).
- Docs: `docs/architecture.md` §84, `CHANGELOG.md`, this file, `MIGRATION.md`. No runtime/trading code touched; no public API change.

## Verification (actually executed, Linux sandbox, fresh clone of origin/main)
- `ruff check .` -> All checks passed
- `pytest tests/` -> 3514 passed, 4 skipped, 45 deselected (integration marker), 0 failed
  (`test_dashboard_serving.py::test_real_v16_build_exists_at_the_resolved_path` requires a built `dist`; it was built first with
  `npm ci && npm run build`, which also confirmed `tsc` + Vite succeed and reproduce the same bundle hashes seen on the operator PC)
- `python -c "import main"` -> OK
- `vulture . --min-confidence 80` -> 43 findings, all in files this change does not touch (none in the new files)
- Helper against the real repo: `fresh` right after a build, `build` after touching a source file.

## Limitations / follow-up
- **`ensure_dashboard.bat` was NOT executed** (no Windows in the sandbox); its logic is covered by the helper tests plus static
  checks only. First real run on Windows should be watched once.
- Linux/macOS launchers (`run_*.sh`) never called `ensure_dashboard.bat`; unchanged here.
- mtime-based: a `git checkout` that rewrites unchanged files can trigger one extra rebuild; harmless.
- `npm audit` reports vulnerable dashboard dependencies; separate work, do not use `npm audit fix --force`.
