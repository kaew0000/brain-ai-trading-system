// ============================================================
// Brain Bot V15 — World Config
// Single source of truth for all world/asset constants.
// ============================================================

export const WORLD_CONFIG = {
  // Tile grid dimensions (logical world units)
  tileSize: 16,

  // Asset paths
  assetRoot: '/assets/world/',
  manifestPath: '/assets/world/manifest.json',

  // NPC sprite sheet layout
  npcFrameWidth: 140,
  npcFrameHeight: 160,
  /** Direction → column index in the 4-frame horizontal sheet */
  npcDirections: { F: 0, B: 1, L: 2, R: 3 } as Record<string, number>,

  // Display scale: each logical tile renders at this many px
  tileRenderScale: 2,

  // Fallback colors when a PNG is missing
  fallback: {
    tile:     0x1a1a2e,
    building: 0x16213e,
    npc:      0x0f3460,
    prop:     0x533483,
  },

  // Water animation
  waterFrames: 9,          // water_0 … water_8
  waterFrameMs: 400,

  // Performance
  spritePoolSize: 256,
  useTextureCache: true,
} as const;

export type WorldConfig = typeof WORLD_CONFIG;
