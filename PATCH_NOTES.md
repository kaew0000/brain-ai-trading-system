# PATCH NOTES — Office World LPC characters (V16 §93)

Branch: `feature/world-lpc-characters-s93`
Base: `main` @ `d30b8ed` (PR #133 merged)
Commit: `feat(world): LPC character sheets for the Office World (V16 §93)` (exactly one)
Series: PR 1 of the "LPC characters + top-down Tiled rooms" plan. Rooms/tilemaps are NOT in this PR.

## What
The 10 uploaded Universal-LPC sheets (64x64 cells, 13 columns x 54 rows) now draw the Office World characters. Roles are the existing NPC roles
(`ceo`, `data_analyst`, `ml_scientist`, `office_worker`, `quant_researcher`, `risk_manager`, `security_officer`, `trader`, `visitor_1`, `visitor_2`), so the
backend, `CHARACTER_TO_ROLE` and the RenderFrame wire format are unchanged. Roles without a sheet (`player`) keep the existing art.

## Findings that shaped the design (verified on the files)
1. The `sit` rows are a sit-on-the-floor sequence, not a chair pose, so `working`/`meeting` stay standing; `sit` is used for `resting` only.
2. `data_analyst`, `ml_scientist`, `quant_researcher`, `risk_manager` each wear one garment layer (`torso_clothes_longsleeve_formal` x2,
   `torso_clothes_tunic`, `torso_jacket_frock`) that supports `walk` but not `idle`/`sit`/`emote`/`run`; those frames draw the torso bare. The importer
   derives this per role from each export's JSON (`unsupportedAnimations`) and the scene falls back to the standing frame (walk frame 0).
3. LPC facing is 4-way orthogonal (up/left/down/right), not isometric; it is drawn as-is in both projections.

## Changes (additive)
- `world/data/assets/lpc_characters.json` + `world/scripts/import_lpc_characters.py`: spec (folder->role, layout, behaviour->animation) and an idempotent importer
  (copies sheets under normalised names, merges credits, writes the `lpc` block of `manifest.json`; other keys untouched; sheet size validated).
- `dashboard_src/public/assets/world/lpc/*.png` (10 sheets), `manifest.json` `lpc` block, `third-party-licenses/lpc_credits.csv` + `LPC_CHARACTERS.md`.
- `dashboard_src/src/pages/world/lpcAssets.ts`: pure helpers (rows/frames/behaviour/fallback), no Phaser.
- `AssetRegistry.ts`: optional `lpc` manifest type, spritesheet loading, `getLpcNPC()`.
- `OfficeScene.tsx`: LPC branch in the characters layer (static frame per behaviour, walk cycle during glides, NEAREST filtering). Used only when
  `lpc.enabled` and the role has a loaded sheet; otherwise the previous iso/legacy path runs unchanged.
- Tests: `world/tests/test_lpc_characters.py` (7), `lpcAssets.test.ts` (8).
- Docs: `docs/architecture.md` §93, `CHANGELOG.md`, this file, `MIGRATION.md`.

## Quality gates (run in the sandbox)
- `ruff check .`: All checks passed. `python -c "import main"`: OK.
- `pytest tests/`: 3546 passed, 4 skipped, 3 failed. The 3 failures are `tests/test_dashboard_serving.py` (need a built dashboard); they fail identically on a clean `main`.
- `pytest world/tests -m ""`: 599 passed. `tsc --noEmit`: clean. `vitest run`: 204 passed (21 files).
- `vulture --min-confidence 80`: only pre-existing findings in `tests/test_weighting_key_namespace.py`; none in the new files.
- NOT run: the browser (no visual check of the live World page in a real Phaser canvas) and `vite build`.

## Not changed
Backend, schema, config, order path, iso art/manifest block, `CHARACTER_TO_ROLE`, legacy 140x160 sheets (still loaded as the fallback).

## Known follow-ups
- `player` sheet (export one more LPC character) and re-exports of the 4 roles with garments that support idle/sit/emote.
- PR 2+: Tiled top-down room maps (office tileset decision needed), Tilemap loader, collision/walkable layers, player-controlled walking, furniture props.
