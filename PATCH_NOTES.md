# PATCH NOTES — Test/Tooling Housekeeping Batch (V16 §70)

Branch: `fix/test-housekeeping-batch` (rebuilt as
`fix/test-housekeeping-batch-v2` on top of the new base — same diff,
see Section-numbering note below)
Original base: `main` @ `544493b` (merge of PR #103, commission/fee
backfill). Re-verified base: `main` @ `9498a05` (merge of PR #104,
news sentiment, §69) — see Section-numbering note.

## Section-numbering note

Originally written and delivered as "§68" against `main` @ `544493b`.
A second, independent branch (news sentiment) was created from the
same base around the same time and also claimed "the section after
§67" — a real collision, flagged in that phase's own docs at the time
(`docs/architecture.md`'s §69 "Section-numbering note"). Kaew merged
news sentiment first (PR #104), so this phase is renumbered §68→§70
here rather than disturbing §69, which was already public on `main` by
the time this merged. No content/behavior changes from the
renumbering — purely this header and cross-references to it. Cherry-
picked cleanly onto the new base (all four affected code files applied
without conflict); only the four docs files needed conflict resolution
for the renumbering itself.

Closes the two remaining Low-severity items from the 2026-08-05
project tracker's Bug Tracker / Risk Register that weren't already
resolved by §65 (HMM contamination), §66/§67 (N+1 fix, per-agent
attribution, fee capture).

## Item 1: `tests/test_execution_factory.py` `os.environ` leak

### Root cause

`TestExecutionFactory._factory(mode)` sets both
`os.environ["EXECUTION_MODE"]` and `config.settings.settings.
EXECUTION_MODE` directly with no teardown, then reloads
`execution.execution_factory` to pick up the change. Flagged in
docs/architecture.md's Hotfix 2026-08-05 section as "Follow-up found
but not fixed here" — latent-only because this file's last test
happens to call `_factory("paper")`, coincidentally leaving both back
at `"paper"`. Order-dependent luck, not a guarantee — a future test
addition or reorder could leak a non-default `EXECUTION_MODE` into
later tests in the same process.

### Fix

Added an autouse, function-scoped `_restore_execution_mode` fixture on
`TestExecutionFactory` that snapshots `os.environ.get("EXECUTION_MODE")`
and `config.settings.EXECUTION_MODE` before each test and restores
both after, regardless of outcome. No changes to any test body or to
`_factory()` itself — purely additive.

## Item 2: `bundle_history.json` phantom SHA (Phase 2E record)

### Root cause

The tracker's Bundle History tab (2026-08-05 snapshot) flagged this
record's `sha` (`d8c7aaf13f0f240d2fe8a86b0d3e48258b6b4683`) as not
existing in the repository, with the real Phase 2E commit being a
different hash. Re-confirmed against current `main`:
`git cat-file -t d8c7aaf13f0f240d2fe8a86b0d3e48258b6b4683` still fails.
The real commit — matching this record's branch, bundle_filename, and
imported_at — is `2426966698d3954d97926f18e1b84588bab1de02`
("feat(execution): merge Phase 2E Execution Wiring & Live
Orchestrator", 2026-07-20 17:19:27 +0700), confirmed via `git log`.

### Fix

Per this repo's own 2026-08-02 stabilization report policy —
inferable-but-not-provable discrepancies get documented, not silently
rewritten — the original `sha` is preserved. This correction is
provable (not merely inferable), so it's recorded explicitly: two new
optional fields on `tools/history.py`'s `BundleRecord` dataclass,
`corrected_sha` and `correction_note`, both defaulting to `None`
(backward compatible with every pre-existing record). Added as real
dataclass fields rather than raw untyped JSON keys because
`BundleHistory.save()` serializes via `dataclasses.asdict()` — an
undeclared field patched only into the JSON would have been silently
stripped the next time any tool run calls `save()`.
`bundle_history.json`'s Phase 2E record now carries both fields.

## Tests

`tests/test_bundle_manager_history.py` — 2 new tests:
`test_corrected_sha_defaults_to_none`,
`test_corrected_sha_round_trips_through_save_and_reload` (the latter
directly proves the fix — that a correction survives a save/reload
cycle rather than being silently dropped).

All pre-existing tests pass unchanged at both verification points.

**Original verification** (`main` @ `544493b`, before §69 existed):
`pytest` → 3143 passed (up from 3141 in §67), 4 skipped, 45
deselected, 0 failures.

**Re-verification at merge time** (`main` @ `9498a05`, after §69's 47
tests landed): `pytest` → **3190 passed** (up from 3188 in §69 — same
+2 delta as the original verification), 4 skipped, 45 deselected,
**0 failures**.

`ruff check . --exclude dashboard_src --exclude dashboard` → all
checks passed, both times. `vulture . --exclude
dashboard_src,dashboard,tests --min-confidence 80` → clean, both
times. `python -c "import main"` → succeeds, both times.
`python -c "import json; json.load(open('bundle_history.json'))"` →
valid JSON.

## Remaining items from the 2026-08-05 tracker

With this batch (and §69, merged just before it), the trading-system-
side backlog from that tracker is now **fully closed** — every item
that required a code change has shipped. Two items remain, both
explicitly out of scope for code changes:
- Binance API 401 (-2015) / IP whitelist — external Binance account
  config, not verifiable or fixable from this repo.
- `fix/office-scene-real-assets` unmerged branch — World-track
  frontend work, paused per Kaew's 2026-09-17 decision to deprioritize
  World development.

## Files changed

`tests/test_execution_factory.py`, `bundle_history.json`,
`tools/history.py`, `tests/test_bundle_manager_history.py`,
`PATCH_NOTES.md`, `MIGRATION.md`, `CHANGELOG.md`,
`docs/architecture.md` (§70, renumbered from §68).
