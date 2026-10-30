# MIGRATION — Office World LPC characters (V16 §93)

## Required
None. No config, schema or data migration. Rebuild the dashboard (`ensure_dashboard`/§84 does this automatically on start) to pick up the new sheets.

## What you will notice
- World characters are drawn from the LPC sheets (64px, crisp pixel art) in both projections. Behaviour still drives the colour ring; `resting` sits on the floor,
  `celebration` raises the arms, everything else stands. Characters walk with a 4-direction cycle while moving between positions.
- Four roles (`data_analyst`, `ml_scientist`, `quant_researcher`, `risk_manager`) only use the walk frames (standing = walk frame 0) because their shirt/jacket
  layer does not support the other animations. Re-export them with a shirt that does, then run the importer again.
- `player` still uses the previous art until a sheet is supplied.

## Switch off / rollback
Set `"enabled": false` in `world/data/assets/lpc_characters.json` and re-run the importer (or edit `manifest.json` `lpc.enabled`), or `git revert` the commit.
The previous iso/legacy art is untouched and takes over immediately.

## Re-import
`python -m world.scripts.import_lpc_characters <dir-or-zip>`; keep the folder names listed in `sourceFolders` of the spec.
