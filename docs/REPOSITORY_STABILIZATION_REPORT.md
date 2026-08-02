# Repository Stabilization Report

**Date:** 2026-08-02
**Branch:** `stabilization/documentation-history-repair`
**Base:** `main` @ `4e0a00e` (Track A through Phase 4C Step 1, Track B
through W6 Asset Pipeline — confirmed via `git ls-remote` before work began)
**Scope:** Documentation and history repair only. Zero runtime code
changes. This report documents what was found (via
`docs/REPOSITORY_AUDIT_REPORT.md`, delivered 2026-08-02, prior to this
phase), what was fixed, what was deliberately left unfixed and why, and
what remains genuinely unverifiable.

---

## 1. Findings (source: prior audit, re-confirmed here)

1. Three merged, tested Track A phases had no `CHANGELOG.md` entry:
   Phase 4A, Phase 4B Step 1, Phase 4B proper.
2. `docs/ROADMAP.md` had been edited exactly once in the repository's
   entire history (the first commit, 2026-07-18) and never updated for
   any of the ~24 PRs merged since.
3. `README.md`'s opening summary paragraph was stale, last meaningfully
   updated around Phase 2E (2026-07-20), never updated for Phase 2F,
   3A, any of 4A-4C, or any Track B phase.
4. Phase 4B Step 3A had no dedicated `docs/architecture.md` section
   (only background prose inside §30).
5. The Track B "performance v1" commit (`9ad1ab5`, merged via PR #5,
   2026-07-20) — a real, merged phase that predates W1 by ten days —
   was not referenced anywhere in `world/WORLD.md` or
   `world/docs/roadmap.md`.
6. `applied/` does not exist anywhere in this repository's history.
7. One branch (`feature/phase4b-step3c-live-ceo-integration`) carries
   three commits — including a duplicate pair — pushed a day-plus
   *after* its actual PR (#15) had already merged. These three commits
   are not reachable from `main`.
8. `bundle_history.json` has exactly 2 records (from 2026-07-20/21) and
   was never updated for any phase since. One of the two records
   (Phase 2E) references a commit SHA (`d8c7aaf...`) that does not
   exist anywhere in the repository.
9. "Phase 2D" appears nowhere in commit messages, `CHANGELOG.md`,
   `CLAUDE.md`, or `docs/architecture.md`.

Full evidence, commands, and reasoning for every item above are in
`docs/REPOSITORY_AUDIT_REPORT.md` (delivered prior to this phase) — not
reproduced in full here to avoid duplicating that document; this report
covers what changed as a result.

---

## 2. Fixes applied this phase

| Finding | Fix | File(s) |
|---|---|---|
| #1 (CHANGELOG gap) | Added three entries — Phase 4A, Phase 4B Step 1, Phase 4B proper — in correct chronological position, content verified against `docs/architecture.md` §26-28 (not reconstructed from memory) | `CHANGELOG.md` |
| #2 (stale ROADMAP) | Rewritten to match verified current state: every phase through 4C Step 1 moved to Completed, "In Progress" emptied (nothing is), "Planned" replaced with the real open items already scoped in `docs/architecture.md`'s own "Next up" sections and `CLAUDE.md`'s "Current Priorities" | `docs/ROADMAP.md` |
| #3 (stale README) | Opening paragraph updated to reference Phase 4C Step 1 and §17-33; added a short Track A/B pointer to `docs/architecture/SEPARATION_POLICY.md` | `README.md` |
| #4 (missing 3A section) | Added as a new, clearly-labeled **retrospective §34** at the end of the document — **no existing section renumbered**. Content reconstructed entirely from commit `c759bec`'s own message and diff, not memory. A forward-reference was added inside §30's existing "Background" paragraph pointing to §34. | `docs/architecture.md` |
| #5 (undocumented pre-W1 phase) | Added a matching historical-background callout to both `world/WORLD.md` (following that file's own established "Phase WN update" callout convention) and `world/docs/roadmap.md` — explicitly labeled "not renumbered as W0" per this phase's own constraint. Also added a "Phase W6 update" callout to `WORLD.md` for consistency with the existing W2-W5 callout pattern (W6 previously had none, despite being covered in §8 and the footer). | `world/WORLD.md`, `world/docs/roadmap.md` |
| #7 (orphan branch) | Documented (§4 below). **Not deleted, not merged, not modified** — branch ref left exactly as-is on the remote, per this phase's explicit "DO NOT delete them" constraint (this phase cannot delete a remote ref from a bundle-based workflow in any case). | This report only |
| #9 (Phase 2D) | Documented as "not verifiable" in `docs/ROADMAP.md`'s new text and in this report. Not invented. | `docs/ROADMAP.md` |

**A factual error was caught and corrected during this phase's own
work**, in the interest of transparency: an early draft of the
pre-W1/W1 date-gap note said "one day" before Phase W1; the actual gap
(`9ad1ab5` 2026-07-19 vs. `d74ba2c` 2026-07-29) is ten days. Caught by
re-verifying the exact commit dates before finalizing, corrected before
this branch's commit — mentioned here rather than silently fixed, since
this phase's entire purpose is factual accuracy.

---

## 3. Deliberately NOT fixed, and why

- **`bundle_history.json` — left completely unchanged.** The Phase 2E
  record's SHA (`d8c7aaf...`) does not exist in this repository
  (`git cat-file -t d8c7aaf...` fails). The commit actually on `main`
  for Phase 2E is `2426966` — a *different* hash. It is reasonable to
  *infer* the record was meant to reference that commit (or an earlier,
  differently-committed version of the same bundle), but this cannot be
  *proven* from repository evidence — the object simply isn't present
  to compare against, and bundles applied via patch rather than a
  hash-preserving fetch routinely produce a new commit hash for
  identical content. Overwriting the SHA with an inferred value would
  present an inference as a verified fact, which this phase's own
  "Never fabricate history" rule forbids. **Left unchanged; this
  paragraph is the documentation the task instructions call for
  instead.**
- **Orphan branch `feature/phase4b-step3c-live-ceo-integration` —
  left exactly as-is.** Contains three commits (`fcf2fb8`, `b834121`,
  `a132ca7`) not reachable from `main`, including duplicate content
  later superseded by Phase W2's own version of the same files (see
  audit report §3/§9). Per this phase's explicit constraints, orphan
  branches are to be documented, not deleted, not rewritten, not
  merged. No action taken beyond the documentation in §1/§4 of this
  report (which repeats, for completeness, what the prior audit already
  established).
- **"Phase 2D"** — no fix attempted; there is nothing to fix without
  inventing a phase that may never have existed. Documented as
  unverifiable in `docs/ROADMAP.md`.
- **`docs/architecture.md` §3-15 (pre-repository-history phases)** —
  not backfilled with real commit references, because none exist in
  this repository to reference. Left exactly as the prior audit found
  them.
- **`docs/CHANGELOG.md` (the frozen, pre-repo-history duplicate at a
  different path from root `CHANGELOG.md`) — left unchanged.** It is a
  legitimate, distinct historical document (the original "V16.5 patch
  consolidation" record), not a competing active changelog; rewriting
  or merging it into the root `CHANGELOG.md` was not requested and
  risks destroying a primary source document for the pre-repository
  period referenced nowhere else.
- **Track B phases W4/W5/W6 — NOT added to the root `CHANGELOG.md`,
  despite being named explicitly in this phase's own instructions.**
  Reasoning: `world/docs/roadmap.md` already documents all six W-phases
  completely and accurately (confirmed in the prior audit); the root
  `CHANGELOG.md` has never once, across all six W-phases (W1 through
  W6), contained a Track B entry — every W-phase PR left it untouched.
  Adding entries for W4-W6 only, while W1-W3 remain absent, would
  create a *new* inconsistency (partial, arbitrary-looking Track B
  coverage in a Track-A-pattern document) rather than repair one, and
  would blur the Track A/B documentation boundary
  `docs/architecture/SEPARATION_POLICY.md` establishes. This judgment
  call is flagged here explicitly rather than silently deviating from
  the literal instruction.

---

## 4. Orphan branches (documented, not touched)

| Branch | Tip | Status |
|---|---|---|
| `feature/phase4b-step3c-live-ceo-integration` | `a132ca7` | Its actual merged content (PR #15) was one commit, `1677653`. Three later commits (`fcf2fb8`, `b834121`, `a132ca7`) were pushed to the same branch name on 2026-07-28/29, after the PR had already merged, and were never merged via any subsequent PR. Not reachable from `main`. Left untouched on the remote. |

No other branch shows evidence of a similar post-merge divergence — every
other `refs/heads/*` branch's tip matches exactly what its corresponding
"Merge pull request" commit brought in (re-verified this phase via
`git merge-base --is-ancestor` against every remote branch, same method
as the prior audit).

## 5. Orphan commits (documented, not touched)

| Commit | Message | Status |
|---|---|---|
| `fcf2fb8` | "docs: add Track A/B separation policy (Trading Engine vs Command World)" | Not reachable from `main`. Content later superseded by Phase W2's independently-authored version of the same files. |
| `b834121` | Byte-identical message to `fcf2fb8`, 5 minutes later | Same as above — a duplicate of the commit immediately before it. |
| `a132ca7` | "docs(world): lock Brain AI Headquarters office architecture" | Not reachable from `main`. |

---

## 6. Verification

Run today, read-only, from this branch (`stabilization/documentation-history-repair`),
after every fix above and before committing:

```
pytest tests/ -q          -> 1885 passed, 0 failed   (Track A — unchanged from pre-stabilization baseline)
world/: pytest tests/ -q  -> 199 passed, 0 failed     (Track B — unchanged from pre-stabilization baseline)
ruff check .               -> All checks passed
vulture . --exclude world  -> 231 findings at default 60%+ confidence (baseline, unchanged —
                               see note below; not introduced by this phase)
```

**Vulture note:** this repository has no `vulture` configuration
(no allowlist, no `pyproject.toml`/`setup.cfg` section) and no CI step
was found invoking it with a fixed baseline to diff against, beyond one
prior fix commit (`fix(world): silence vulture false positives on
abstract interface stubs`) and an unrelated, apparently-unapplied
`vulture_fix.patch` at the repo root (targets `database/db.py`'s
`__exit__` unused-`tb` parameters — not touched by this phase, since
`database/` is runtime code). The 231 findings at default confidence
are overwhelmingly FastAPI route handlers vulture cannot see are called
via decorator registration — a well-known class of vulture false
positive, not a real issue, and **identical before and after this
phase's changes** (this phase touches zero `.py` files, so this is
trivially true and was spot-checked rather than exhaustively diffed).

**Scope compliance check:**
```
git diff --name-only main
```
→ `CHANGELOG.md`, `README.md`, `docs/ROADMAP.md`, `docs/architecture.md`,
`world/WORLD.md`, `world/docs/roadmap.md` — six files, all inside this
phase's explicitly Allowed list. Zero files under `agents/`, `execution/`,
`portfolio/`, `learning/`, `dashboard/`, `brain/`, `risk/`, `exchange/`,
`strategy/`, `tests/`, or any world runtime path were touched.
`bundle_history.json` was considered and deliberately left unchanged
(§3).

---

## 7. Future recommendations

- Wire a CI check that fails a PR if `CHANGELOG.md` has no new
  `## [Unreleased]` header when `docs/architecture.md` gains a new
  numbered section — would have caught finding #1 automatically.
- Either delete `docs/ROADMAP.md` in favor of `docs/architecture.md` +
  `CLAUDE.md` (which are both kept current) or add the same CI
  discipline `world/docs/roadmap.md` already has, where every phase PR
  is required to touch its track's roadmap file.
- Decide, once, whether `bundle_history.json` is meant to be a
  permanent per-phase ledger (in which case it needs the same
  "every phase PR must update it" CI discipline) or was a one-time
  import-tracking mechanism for the original ten-bundle consolidation
  only (in which case it should say so explicitly, to stop future
  audits re-flagging it as "abandoned").
- Delete or reset `feature/phase4b-step3c-live-ceo-integration`'s ref
  to `1677653` (its actual merged commit) in a future housekeeping
  pass — outside this phase's read-only-on-branches constraint, but
  worth doing deliberately rather than leaving the drift in place
  indefinitely.
- Consider a repository-wide branch-cleanup pass: every one of the 18+
  feature branches found in this and the prior audit is still present
  on the remote after merging. Not a correctness problem, but it makes
  "which branches are actually still relevant" progressively harder to
  answer without an audit like this one.
