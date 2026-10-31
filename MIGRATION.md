# MIGRATION — Walkable tile Office World + mode-aware World (V16 §94)

## Required
None. No schema or data migration. Rebuild the dashboard (`ensure_dashboard`/§84 does this on start).

## What you will notice
- The World tab shows a walkable office. Move with WASD / arrows or click a spot; click a room in the room list and the avatar walks there. Near an NPC press `E`
  (or the Talk button); in Studio this opens a chat with it. Pick the avatar in the HUD (remembered in localStorage).
- A mode badge (PAPER / TESTNET / TRAINING / LIVE · real money) sits next to the connection status.
- System Pulse PnL / win rate now cover the process's own lane only (live+testnet -> LIVE, paper -> TRAINING). Set `WORLD_LANE_SCOPED_PORTFOLIO=false` for the old combined figures.

## Switch off / rollback
- Tile world only: set `tileWorld.enabled` to `false` in `dashboard_src/public/assets/world/manifest.json`; the isometric `OfficeScene` takes over immediately.
- Lane scoping only: `WORLD_LANE_SCOPED_PORTFOLIO=false`.
- Everything: `git revert` the commit.

## Rebuild the map
`python -m world.scripts.build_tile_world` (a test fails if the committed files differ from a rebuild).
