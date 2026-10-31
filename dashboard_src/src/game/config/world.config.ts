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

  // Live view (V16 §82)
  /** NPC glide duration between two frames. Kept below the default 2 s world tick so a step finishes before the next. */
  characterTweenMs: 1800,
  /** A jump larger than this (px) is a teleport / re-layout: snap instead of sliding across the room. */
  characterSnapDistancePx: 240,
  /** Frame refetch period while /ws/world is not LIVE (when LIVE, frames refetch on each simulation tick message). */
  frameFallbackPollMs: 5000,
  /** System Pulse refresh period. */
  pulsePollMs: 5000,
  /** A real-data snapshot older than this many seconds is flagged STALE in the System Pulse. */
  pulseStaleSeconds: 180,
  /** Recent events listed in the System Pulse. */
  pulseRecentEvents: 5,

  // Tile world (V16 §94) — the walkable office that replaces the isometric Office scene
  tileWorld: {
    /** Player walking speed. */
    playerSpeedPxPerSec: 150,
    /** NPC walking speed; below the player's so the player can always catch up with someone. */
    npcSpeedPxPerSec: 80,
    /** An NPC this close (px, feet to feet) can be talked to with E / a click. */
    interactRangePx: 72,
    /** Feet collision box: half width and height (px), anchored at the feet point. */
    hitboxHalfWidthPx: 10,
    hitboxHeightPx: 8,
    /** Feet point sits this many px below the top of the tile the character stands on. */
    footOffsetPx: 40,
    /** Camera follow smoothing (0..1 per frame). */
    cameraLerp: 0.12,
    cameraZoom: 1.25,
    canvasHeightPx: 540,
    /** A 'walking' NPC picks a new waypoint in its room every N simulation ticks. */
    wanderEveryTicks: 4,
    /** localStorage key of the player's chosen avatar. */
    avatarStorageKey: 'brainbot.world.avatar',
    /** Upper bound on tiles a path search may expand (map is ~1k tiles; guards against a bad map). */
    maxPathNodes: 4096,
  },
} as const;

export type WorldConfig = typeof WORLD_CONFIG;
