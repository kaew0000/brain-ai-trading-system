# CLEANUP_REPORT

## Removed — confirmed unnecessary before deleting

| Item | Why removed |
|---|---|
| `findstr` (empty file, repo root) | 0 bytes, no content, no references anywhere in the codebase |
| `uvicorn.txt` (repo root) | Personal scratch notes (mixed Thai/English: `uvicorn` run commands and a Windows `for /d /r` cache-clear one-liner) — the actual run commands are already documented properly in `README.md` |
| `paper_metrics_503_fix.patch` (repo root) | A raw unified diff sitting in the tree. Verified the exact change it describes (returning `200` with an `enabled: false` flag instead of `503` from `/paper_trades` when the paper engine isn't running) is **already present, verbatim docstring included**, in `api/app.py`. Dead, already-applied patch artifact. |
| `{config,data,features,regime,decision,execution,analytics,risk,utils,tests,vendors,logs}` (literal directory name) | An empty directory whose name is itself a shell brace-expansion pattern — clearly created by running something like `mkdir {a,b,c}` in a shell that doesn't do brace expansion (e.g. `sh` instead of `bash`). Empty, no files inside. |
| `__pycache__/`, `*.pyc`, `.pytest_cache/`, `.ruff_cache/` (repo-wide) | Regenerable build artifacts |
| `node_modules/` under `dashboard_src/` (287 MB) | Regenerable via `npm install`; excluded from the repo, listed in `.gitignore` |
| `*.db` files (`brain_bot_journal.db`, `brain_bot_v13.db`) | Runtime data, not source — see `GITHUB_READY_CHECKLIST.md` for why these shouldn't be committed |
| Duplicate top-level `V16_AUDIT_REPORT.md` / `V16_PHASE1_MULTISYMBOL_MIGRATION.md` inside `Brain_Bot_PATCH/` (source archive, not the output repo) | Identical content already present at `docs/` inside the merge base |

## NOT removed — flagged instead of deleted

- **`BrainBot_V16_Project_Knowledge.zip` contents** (20+ planning
  markdown files like `06_WORLD_ENGINE.md`, `22_RECOVERY_ENGINE.md`).
  These describe aspirational/future architecture that doesn't match
  the current code. Per the "never remove working code/content without
  evidence it's obsolete" rule, and since these aren't code, I left
  them out of the production repo rather than guessing whether you
  still want them — see `MERGE_REPORT.md` §5. Say the word and I'll
  add them under `docs/planning/`.
- **Nine historical audit reports under `reports/`** (`BUG_REPORT.md`,
  `SYSTEM_AUDIT.md`, `PERFORMANCE_AUDIT.md`, etc., dated V14/V15) — kept
  as historical record even though a newer `docs/` folder now exists,
  since they cover different content, not superseded versions of the
  same document (verified by diffing filenames and content — no
  overlap).
- **391 ruff findings and 6 vulture findings** — real but pre-existing
  style/dead-code debt, not touched in this merge to keep the diff
  focused on the actual patch integration. Tracked in `TEST_REPORT.md`
  with a recommendation to fix as a separate follow-up commit.

## Caught during final verification pass

The `p2_opportunity_ranker` snapshot itself (not RUN) shipped its own
`.env` and `brain_bot_v13.db` at its root. Both were removed from the
final output:

- `.env` — inspected first; its contents were the template header only
  (`# Copy this file to .env and fill in your values`), not live
  secrets, but a stray root `.env` sitting next to `.env.example` is
  still wrong for a repo meant to go to GitHub, so it was deleted.
- `brain_bot_v13.db` (225 KB SQLite file) — runtime data, same
  reasoning as the `.db` exclusion decision in `MERGE_REPORT.md` §4.

## Not attempted

Deduplicating/cleaning the 10 raw patch `.zip` files themselves
(`Brain_Bot_PATCH/*.zip`) — those live in your original upload, not in
`Brain_Bot_V16_GitHub_Ready/`, which is the only directory intended to
go to GitHub. They're not part of the output repo, so there was nothing
to clean there.
