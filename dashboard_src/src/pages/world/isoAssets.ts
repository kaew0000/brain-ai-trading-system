// dashboard_src/src/pages/world/isoAssets.ts
// Phase W-ISO-2 — pure helpers for the isometric art set (props + per-character
// pose sheets). Everything here is data-driven from the `iso` block of
// public/assets/world/manifest.json (written by world/scripts/generate_iso_assets.py):
// sizes, anchors, footprints and heights come from the manifest, never from constants
// in the scene. Kept free of Phaser so it is unit-testable in jsdom.

export interface IsoPropEntry {
  path: string
  width: number
  height: number
  /** Normalised (0..1) point inside the sprite that sits on the command's screen x/y (footprint base centre). */
  anchor: [number, number]
  footprint: [number, number]
  heightPx: number
}

export interface IsoCharacterConfig {
  frameWidth: number
  frameHeight: number
  anchor: [number, number]
  poses: string[]
  behaviorPose: Record<string, string>
  seatedWorkingPose: string
}

export interface IsoManifest {
  version: string
  tile: { width: number; height: number }
  character: IsoCharacterConfig
  props: Record<string, IsoPropEntry>
  npc: Record<string, string>
  /** backend asset id (e.g. "furniture.desk") -> key in `props` */
  assetIds: Record<string, string>
  /** W-ISO-3 (optional: older manifests lack it) — 4-direction walk strips per character. */
  walk?: IsoWalkConfig
  /** W-ISO-3 (optional) — floor tile key -> image path (64x32 diamond). */
  tiles?: Record<string, string>
}

export type IsoDirection = 'se' | 'sw' | 'nw' | 'ne'

export interface IsoWalkConfig {
  frameWidth: number
  frameHeight: number
  directions: IsoDirection[]
  frames: number
  fps: number
  /** character id -> sheet path (rows = directions, cols = frames) */
  sheets: Record<string, string>
}

export interface ResolvedIsoProp {
  key: string
  entry: IsoPropEntry
}

/** Backend RenderCommand.assetId -> iso prop, or null when no iso art exists (caller falls back). */
export function resolveIsoProp(manifest: IsoManifest | null | undefined, assetId: string | null | undefined): ResolvedIsoProp | null {
  if (!manifest || !assetId) return null
  const key = manifest.assetIds[assetId]
  const entry = key ? manifest.props[key] : undefined
  return key && entry ? { key, entry } : null
}

/** Pose name for a behaviour. Seated `working` pose only when the character has an iso sheet and seating is requested. */
export function isoPoseName(config: IsoCharacterConfig, behavior: string, seated: boolean): string {
  if (seated && behavior === 'working') return config.seatedWorkingPose
  return config.behaviorPose[behavior] ?? config.behaviorPose.idle ?? config.poses[0]
}

/** Frame index inside a character's pose strip; falls back to frame 0 for an unknown pose. */
export function isoPoseFrame(config: IsoCharacterConfig, pose: string): number {
  const i = config.poses.indexOf(pose)
  return i >= 0 ? i : 0
}

/** Phaser origin for a prop: places the footprint base centre on the command position. */
export function isoPropOrigin(entry: IsoPropEntry): [number, number] {
  return [entry.anchor[0], entry.anchor[1]]
}

/** Extra depth for a prop so it sorts by its *front* edge, derived from the manifest footprint:
 *  half the footprint depth (tiles) times the tile height. Data-driven, no scene constants. */
export function isoPropDepthOffset(manifest: IsoManifest, entry: IsoPropEntry): number {
  return (entry.footprint[1] / 2) * manifest.tile.height
}

/** Which character ids have an iso pose sheet. */
export function hasIsoCharacter(manifest: IsoManifest | null | undefined, characterId: string): boolean {
  return !!manifest?.npc?.[characterId]
}

/** Screen-space movement (dx right, dy down) -> iso facing. Zero movement keeps `fallback`. */
export function isoDirectionFromDelta(dx: number, dy: number, fallback: IsoDirection = 'se'): IsoDirection {
  if (dx === 0 && dy === 0) return fallback
  if (dy >= 0) return dx >= 0 ? 'se' : 'sw'
  return dx >= 0 ? 'ne' : 'nw'
}

/** Walk-strip frame position (column, row) for a direction and elapsed time; null when the character has no walk sheet. */
export function isoWalkFrame(
  manifest: IsoManifest | null | undefined,
  characterId: string,
  direction: IsoDirection,
  elapsedMs: number,
): { path: string; col: number; row: number } | null {
  const walk = manifest?.walk
  const path = walk?.sheets?.[characterId]
  if (!walk || !path) return null
  const row = Math.max(0, walk.directions.indexOf(direction))
  const col = Math.floor((Math.max(0, elapsedMs) / 1000) * walk.fps) % walk.frames
  return { path, col, row }
}

/** Floor tile image path by key (e.g. 'floor_light'), or null when the manifest predates W-ISO-3. */
export function isoTilePath(manifest: IsoManifest | null | undefined, key: string): string | null {
  return manifest?.tiles?.[key] ?? null
}

/** Floor tile per room (keys of `IsoManifest.tiles`); anything not listed gets the light office tile. */
const ISO_ROOM_FLOOR_TILES: Record<string, string> = {
  lobby: 'floor_wood',
  hallway: 'floor_wood',
  elevator: 'floor_dark',
  'command-hall': 'floor_carpet',
  'ai-council': 'floor_carpet',
}

export function isoFloorTileKey(roomId: string): string {
  return ISO_ROOM_FLOOR_TILES[roomId] ?? 'floor_light'
}

export interface IsoFloorTileLayout {
  /** Tile centres, back (top) to front (bottom). */
  tiles: Array<{ x: number; y: number }>
  tileWidth: number
  tileHeight: number
  count: number
}

/**
 * Splits the room's floor diamond (centre cx,cy; half width; height ratio) into a count x count grid of
 * iso tiles. `nativeTileWidth` (the tile art's width) picks the count; the tile is then stretched so the
 * grid exactly fills the diamond. For the default 640px floor and 64px art that is 10 x 10 tiles.
 */
export function isoFloorTileLayout(
  cx: number,
  cy: number,
  halfWidth: number,
  ratio: number,
  nativeTileWidth = 64,
): IsoFloorTileLayout {
  const count = Math.max(1, Math.round((halfWidth * 2) / nativeTileWidth))
  const tileWidth = (halfWidth * 2) / count
  const tileHeight = tileWidth * ratio
  const tiles: Array<{ x: number; y: number }> = []
  for (let i = 0; i < count; i++) {
    for (let j = 0; j < count; j++) {
      tiles.push({ x: cx + ((i - j) * tileWidth) / 2, y: cy + ((i + j - (count - 1)) * tileHeight) / 2 })
    }
  }
  tiles.sort((a, b) => a.y - b.y)
  return { tiles, tileWidth, tileHeight, count }
}
