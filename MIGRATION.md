# MIGRATION — Fix: Dangling `signals_pre_w14_2d_1` FK Breaks Trade Journaling

## Do you need to do anything?

**Yes, one step — but it's the same step you always do.**

## Step 1: Import this bundle, restart the bot

That's it for the fix to take effect. `migration_001`'s repair pass
(Part A) is already wired into the automatic every-boot migration
sequence (`database/migrations/runner.py`, unchanged), the same way
every migration in this project always has been. The next time the
bot boots after this bundle is imported, it will:

1. Detect any table whose FK still dangles from the old bug
   (`trades`, and/or `ai_explanations` if it already exists on your
   database).
2. Rebuild just that table from the current, correct schema — no data
   is lost, no other column changes, row counts are preserved.
3. Log the repair the same way every other migration step already
   logs to `logs/brain_bot.log`.

Nothing to configure, no flag to flip. This is idempotent — if there's
nothing dangling (or the repair already ran once), it's a silent
no-op on every subsequent boot.

## Step 2 (optional): inspect or repair a copy first, without booting

If you'd rather see exactly what's dangling on your real file before
trusting the automatic path — or want to repair a **scratch copy** and
verify it independently first — use the new standalone script:

```
# Report only — writes nothing:
python -m database.migrations.migration_002_repair_dangling_signals_fk brain_bot_v13.db

# Actually apply the repair:
python -m database.migrations.migration_002_repair_dangling_signals_fk brain_bot_v13.db --apply
```

`--dry-run` behavior is the default (no flag needed) — you have to
explicitly pass `--apply` for it to write anything. This script is
**not** part of the automatic boot sequence; it's a fully manual tool.
Recommended sequence if you want extra confidence before restarting:

```
copy brain_bot_v13.db brain_bot_v13.db.scratch-copy
python -m database.migrations.migration_002_repair_dangling_signals_fk brain_bot_v13.db.scratch-copy --apply
# inspect brain_bot_v13.db.scratch-copy — confirm it looks right —
# then just restart the bot normally; Step 1 handles the real file.
```

## What this does NOT require

- No schema version bump, no config change.
- No changes to `journal/journal_v2.py` or anything that writes trades
  — only the stored FK *target* on the affected table(s) changes.
- No downtime beyond your normal restart.

## If you want to know exactly what was affected on your real file

The automatic path (Step 1) logs which tables it repaired, if any, to
`logs/brain_bot.log` under the existing `[0/9] running migrations`
startup line. Grep for `fk_repaired` after your next restart if you
want to confirm.
