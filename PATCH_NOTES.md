# PATCH NOTES — Walkable tile Office World + mode-aware World (V16 §94)

Branch: `feature/world-tile-office-s94`
Base: `main` after PR #134 (§93 LPC characters) merged
Commit: `feat(world): walkable tile Office World, playable avatar, mode-aware World (V16 §94)` (exactly one)

## What
1. A new top-down office world built from the supplied CoolSchool tileset replaces the isometric Office scene (kept as fallback).
2. The player walks it (WASD / arrows / click-to-move, collision with walls and furniture); the 16 NPCs go where the simulation says and can be talked to (`E`, click).
3. The World works in paper / testnet / live / training: it labels the mode and its portfolio figures follow the process's execution lane.

## Root causes (reproduced before any change)
- Characters were display-only (no input, no collision; positions only from backend render commands).
- `portfolio_payload()` read `journal.get_daily_stats()` without `execution_lane`: with LIVE +50 and TRAINING -50 every mode showed `dailyPnl = 0.0`
  (`tests/test_world_mode.py::test_portfolio_summary_is_scoped_to_the_processs_lane` fails on the previous exporter).
- Found only by running the built dashboard in headless Chromium: the scene was never handed data that arrived before it was created (no NPCs drawn), and `setAvatar`
  touched `scene.textures` before boot (crash on every mount after the first). Both fixed.

## Files
Backend: `telemetry/world_export.py`, `api/world_api.py`, `config/settings.py` (one flag), `tests/test_world_export.py` (fake journal accepts `execution_lane`).
Build: `world/scripts/build_tile_world.py`, `world/data/assets/tile_world.json`, `world/data/assets/source/`.
Assets: `dashboard_src/public/assets/world/tile/*`, `manifest.json` (+`tileWorld`), `third-party-licenses/COOLSCHOOL_TILESET.md`.
Frontend: `pages/world/{tileWorld.ts,modeBadge.ts,types.ts,api.ts,WorldPage.tsx}`, `components/{TileWorldScene,ModeBadge,StudioView}.tsx`, `game/config/world.config.ts`, `game/assets/AssetRegistry.ts` (type only).
Docs: `docs/architecture.md` §94, `CHANGELOG.md`, this file, `MIGRATION.md`.

## Impact
No change to order execution, sizing, risk or journal writes. The lane scoping changes only what the World displays. Existing endpoints keep their wire format.
