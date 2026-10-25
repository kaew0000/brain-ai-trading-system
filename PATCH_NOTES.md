# PATCH NOTES — World isometric art pipeline (V16 §80, W-ISO-2)

Branch: `feature/world-iso-assets`
Base: `main` @ `d5efa29` (PR #118 merged) plus later `sync bundle history` commits
Commit: `feat(world): isometric art pipeline + meeting/resting/seated sprites (V16 §80)` (exactly one)

## Root cause / gap
W-ISO-1 only re-projected existing top-down art. NPC sheets are 4 facing frames, so behaviour never selected a sprite, and the
backend had no `meeting`/`resting` sprites (W8 fallback). Verified in `OfficeScene.tsx`, `assetMapping.ts`,
`render_config.py`, `character_assets.json`.

## Files
- New: `world/scripts/generate_iso_assets.py`, `world/data/assets/iso_assets.json`, `dashboard_src/public/assets/world/iso/**`,
  `dashboard_src/src/pages/world/isoAssets.ts`, `world/tests/test_iso_assets.py`, `.../tests/isoAssets.test.ts`,
  `dashboard_src/public/third-party-licenses/ISO_ASSETS.md`
- Modified: `render_config.py`, `animation_controller.py`, `character_assets.schema.json`, backend asset JSON (additive),
  frontend `manifest.json` (+`iso`), `AssetRegistry.ts`, `OfficeScene.tsx`, tests, docs, CHANGELOG

## Impact
Isometric mode: iso props and pose frames. Orthographic: unchanged except the meeting ring colour (purple, was green).

## Regenerate
`python -m world.scripts.generate_iso_assets` (`--check` in CI)
