# MERGE_REPORT

## 0. Method

Every claim below comes from an actual command run against the extracted
archives during this merge (file diffs, `ast`-based def/method comparison,
timestamp inspection) — nothing here is inferred from filenames alone.

## 1. Critical discovery that changed the merge strategy

`Brain_Bot_RUN`'s newest file (`main.py`) is dated **2026-07-05**. Every
file in every patch bundle is dated **2026-07-15 through 2026-07-17** —
i.e. strictly *after* RUN. No file in RUN (excluding logs/caches/the DB)
has a modification time after 2026-07-05. **RUN is the stale base; the
patches are the newer development, not the other way around.**

## 2. Patch inventory

| Bundle | Type | Date | Files (.py) | Already applied in RUN? |
|---|---|---|---|---|
| brain_bot_v16_phase1_patch | full snapshot | 07-15 00:26 | 111 | NO |
| brain_bot_v16_fix1_risk_consolidation | incremental patch | 07-15 07:35 | 2 | NO |
| brain_bot_v16_fix2_p0a_p0b_p0d | incremental patch | 07-16 06:03 | 7 | NO |
| brain_bot_v16_p1a_dashboard_auth | incremental patch | 07-16 06:31 | 4 | NO |
| brain_bot_v16_p1b1_dynamic_risk | incremental patch | 07-16 17:01 | 10 | NO |
| brain_bot_v16_merged_fix1_fix2_p1a_p1b1 | full snapshot | 07-16 23:51 | 115 | NO (superseded by newer full snapshots below) |
| brain_bot_v16_p1c_multisymbol_foundation | full snapshot | 07-17 00:25 | 117 | NO (superseded) |
| brain_bot_v16_phase2_part1_scanner | incremental patch | 07-17 01:00 | 5 | NO |
| **brain_bot_v16_consolidated_964** | full snapshot | 07-17 09:25 | 120 | NO (superseded by p2, see below) |
| **brain_bot_v16_p2_opportunity_ranker** | full snapshot | **07-17 09:41 (newest)** | 127 | **Used as merge base** |
| BrainBot_V16_Project_Knowledge | docs only, no code | n/a | 0 | Reference material, not merged (see §5) |

Verification that `p2_opportunity_ranker` supersedes everything older:

- File-for-file diff against `consolidated_964`: zero files removed;
  only additions (`ranking/` module + its test) and three small
  content updates (`config/settings.py`, `database/schema_v13.sql`,
  `docs/architecture.md`).
- Every `.py` file present in the five true incremental patches
  (fix1, fix2, p1a, p1b1, phase2_part1_scanner) is also present in
  `p2_opportunity_ranker` — none went missing.

**Conclusion: `p2_opportunity_ranker` is a strict superset of every
other patch bundle and is the correct single base for the backend.**

## 3. Full diff: RUN vs. p2_opportunity_ranker (backend only)

Recursive diff, excluding `__pycache__`, `.pytest_cache`, `dashboard`,
`dashboard_src`, `reports`, `*.db`, `logs`, `.env*`:

- **0 files exist only in RUN** (nothing backend-side is unique to RUN)
- **12 files/dirs exist only in the patch** — all net-new: `docs/`,
  `ranking/` (5 files), `scanner/` module test, plus 6 new test files
  (`test_api_auth.py`, `test_execution_coordinator.py`,
  `test_market_scanner.py`, `test_opportunity_ranker.py`,
  `test_p1b1_dynamic_risk.py`, `test_v16_execution_idempotency.py`),
  and `utils/systemd_notify.py`.
- **18 files differ** between RUN and the patch. AST-level comparison
  (top-level function/class/method sets) of all 18 shows the changes
  are additive/refactor, with one item requiring manual verification —
  see `CONFLICT_REPORT.md` §1 for that one item's resolution.

## 4. What was carried over from RUN unchanged

Since none of RUN's backend content is unique, only non-backend assets
came from RUN:

- `dashboard/` — built frontend static assets (not touched by any patch)
- `dashboard_src/` — frontend source (not touched by any patch;
  `node_modules/` excluded — regenerate with `npm install`)
- `reports/` — historical audit documents (V14/V15 era; distinct from
  the patch's newer `docs/`, confirmed by content, not just by name)
- `.gitignore`, `.env.example` — repo hygiene files absent from every
  patch bundle

`Brain_Bot_RUN/.env` (live secrets) and the two `.db` files
(`brain_bot_journal.db`, `brain_bot_v13.db`) were **deliberately not
copied** into a GitHub-bound repository. See `GITHUB_READY_CHECKLIST.md`.

## 5. Not merged

- `BrainBot_V16_Project_Knowledge.zip` — a set of 20+ freeform planning
  markdown files (`06_WORLD_ENGINE.md`, `22_RECOVERY_ENGINE.md`, etc.)
  describing future/aspirational architecture, not current code. These
  don't correspond to anything in the code tree and look like design
  notes rather than shipped documentation, so they were left out of the
  production repo rather than presented as current-state docs. Flagging
  for your review rather than silently discarding — happy to add them
  under `docs/planning/` if you want them preserved.
- `V16_AUDIT_REPORT.md` / `V16_PHASE1_MULTISYMBOL_MIGRATION.md` at the
  top level of `Brain_Bot_PATCH/` — identical content already present
  inside `p2_opportunity_ranker/docs/`, so the loose top-level copies
  were treated as duplicates and not separately merged.

## 6. Result

Single merge base, no manual three-way merges required at the file
level (the "MANUAL MERGE" bucket predicted by the task brief turned out
to be empty once the chronology was established — see §1). Everything
else was SAFE MERGE or ALREADY PRESENT. Full per-file classification in
`CONFLICT_REPORT.md`.
