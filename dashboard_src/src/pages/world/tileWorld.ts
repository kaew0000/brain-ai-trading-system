// dashboard_src/src/pages/world/tileWorld.ts
// V16 §94 — pure logic of the walkable tile world: map parsing, collision, path finding, which tile an NPC
// heads for in each behaviour, rooms and interaction range. Free of Phaser and the DOM (except
// isTypingTarget's duck-typed element) so everything is unit-testable in jsdom. The map itself is built by
// world/scripts/build_tile_world.py from world/data/assets/tile_world.json; this file only reads it.

import { WORLD_CONFIG } from '../../game/config/world.config'
import { lpcAnimationName, type LpcDirection, type LpcManifest } from './lpcAssets'

export type Tile = [number, number]

export interface TileSeat {
  tile: Tile
  facing: LpcDirection
  /** Backend character id that works here, or null for a spare seat. */
  character: string | null
}

export interface TileRoom {
  /** Backend room id (RoomActivity.roomId). */
  id: string
  name: string
  /** x, y, w, h in tiles (interior only). */
  rect: [number, number, number, number]
  door: Tile
  meet: Tile
  seats: TileSeat[]
  wander: Tile[]
}

export interface TileProp {
  frame: string
  /** Bottom-centre anchor, world px. */
  x: number
  y: number
  depth: number
  room: string
}

export interface TileMap {
  version: string
  tileSize: number
  cols: number
  rows: number
  width: number
  height: number
  tiles: string[]
  floor: number[][]
  collision: string[]
  props: TileProp[]
  rooms: TileRoom[]
  spawn: { tile: Tile; facing: LpcDirection }
}

export interface TileWorldManifest {
  enabled: boolean
  version: string
  atlas: { image: string; data: string }
  map: string
  defaultAvatar: string
}

export interface Point {
  x: number
  y: number
}

const FACINGS: LpcDirection[] = ['up', 'left', 'down', 'right']

function isTile(v: unknown): v is Tile {
  return Array.isArray(v) && v.length === 2 && v.every((n) => Number.isInteger(n))
}

/** Validates the wire shape of office.map.json; throws a descriptive Error instead of returning a half-usable map. */
export function parseTileMap(raw: unknown): TileMap {
  const m = raw as Partial<TileMap> | null
  const fail = (why: string): never => {
    throw new Error(`invalid tile map: ${why}`)
  }
  if (!m || typeof m !== 'object') return fail('not an object')
  if (!Number.isInteger(m.tileSize) || m.tileSize! <= 0) fail('tileSize')
  if (!Number.isInteger(m.cols) || !Number.isInteger(m.rows) || m.cols! <= 0 || m.rows! <= 0) fail('cols/rows')
  if (!Array.isArray(m.collision) || m.collision.length !== m.rows || m.collision.some((r) => typeof r !== 'string' || r.length !== m.cols)) {
    fail('collision rows must be rows strings of cols characters')
  }
  if (!Array.isArray(m.floor) || m.floor.length !== m.rows || m.floor.some((r) => !Array.isArray(r) || r.length !== m.cols)) fail('floor')
  if (!Array.isArray(m.tiles) || m.tiles.length === 0) fail('tiles')
  if (m.floor!.some((r) => r.some((i) => !Number.isInteger(i) || i < 0 || i >= m.tiles!.length))) fail('floor index out of range')
  if (!Array.isArray(m.props) || !Array.isArray(m.rooms)) fail('props/rooms')
  for (const room of m.rooms!) {
    if (!room.id || !isTile(room.door) || !isTile(room.meet) || !Array.isArray(room.seats) || !Array.isArray(room.wander)) fail(`room ${room?.id}`)
    for (const s of room.seats) if (!isTile(s.tile) || !FACINGS.includes(s.facing)) fail(`seat in ${room.id}`)
  }
  if (!m.spawn || !isTile(m.spawn.tile) || !FACINGS.includes(m.spawn.facing)) fail('spawn')
  return m as TileMap
}

/** True for out-of-bounds tiles and for wall / furniture tiles. */
export function isBlockedTile(map: TileMap, tx: number, ty: number): boolean {
  if (tx < 0 || ty < 0 || tx >= map.cols || ty >= map.rows) return true
  return map.collision[ty][tx] === '#'
}

export function worldToTile(map: TileMap, x: number, y: number): Tile {
  return [Math.floor(x / map.tileSize), Math.floor(y / map.tileSize)]
}

/** Feet point (px) of a character standing on `tile`. */
export function footPoint(map: TileMap, tile: Tile): Point {
  return { x: (tile[0] + 0.5) * map.tileSize, y: tile[1] * map.tileSize + WORLD_CONFIG.tileWorld.footOffsetPx }
}

/** Tile a feet point stands on. footPoint() keeps the feet inside their tile (footOffsetPx < tileSize). */
export function tileOfFeet(map: TileMap, p: Point): Tile {
  return worldToTile(map, p.x, p.y)
}

/** Whether the feet box centred at `p` overlaps no blocked tile. */
export function canStandAt(map: TileMap, p: Point): boolean {
  const { hitboxHalfWidthPx: hw, hitboxHeightPx: hh } = WORLD_CONFIG.tileWorld
  for (const [cx, cy] of [[p.x - hw, p.y - hh], [p.x + hw, p.y - hh], [p.x - hw, p.y], [p.x + hw, p.y]]) {
    const [tx, ty] = worldToTile(map, cx, cy)
    if (isBlockedTile(map, tx, ty)) return false
  }
  return true
}

/** Moves by (dx, dy) one axis at a time so the character slides along walls instead of sticking to them. */
export function moveWithCollision(map: TileMap, from: Point, dx: number, dy: number): Point {
  let { x, y } = from
  if (dx !== 0 && canStandAt(map, { x: x + dx, y })) x += dx
  if (dy !== 0 && canStandAt(map, { x, y: y + dy })) y += dy
  return { x, y }
}

/**
 * Shortest 4-neighbour path from `from` to `to` (both included). A blocked or unreachable target resolves to the
 * reachable tile nearest to it (so clicking a desk walks you up to the desk). Returns [] when already there and
 * null when `from` itself is blocked.
 */
export function findPath(map: TileMap, from: Tile, to: Tile): Tile[] | null {
  if (isBlockedTile(map, from[0], from[1])) return null
  const key = (t: Tile) => t[1] * map.cols + t[0]
  const prev = new Map<number, number>([[key(from), -1]])
  const queue: Tile[] = [from]
  let best: Tile = from
  let bestScore = Math.abs(from[0] - to[0]) + Math.abs(from[1] - to[1])
  let expanded = 0
  for (let head = 0; head < queue.length; head++) {
    const cur = queue[head]
    if (cur[0] === to[0] && cur[1] === to[1]) {
      best = cur
      break
    }
    if (++expanded > WORLD_CONFIG.tileWorld.maxPathNodes) break
    const score = Math.abs(cur[0] - to[0]) + Math.abs(cur[1] - to[1])
    if (score < bestScore) {
      best = cur
      bestScore = score
    }
    for (const [dx, dy] of [[1, 0], [-1, 0], [0, 1], [0, -1]] as const) {
      const next: Tile = [cur[0] + dx, cur[1] + dy]
      if (isBlockedTile(map, next[0], next[1]) || prev.has(key(next))) continue
      prev.set(key(next), key(cur))
      queue.push(next)
    }
  }
  const path: Tile[] = []
  for (let k = key(best); k !== -1; k = prev.get(k) as number) path.push([k % map.cols, Math.floor(k / map.cols)])
  return path.reverse()
}

/** The room whose interior contains `tile`, or null (walls, doorways). */
export function roomAtTile(map: TileMap, tile: Tile): TileRoom | null {
  for (const room of map.rooms) {
    const [x, y, w, h] = room.rect
    if (tile[0] >= x && tile[0] < x + w && tile[1] >= y && tile[1] < y + h) return room
  }
  return null
}

export function roomById(map: TileMap, id: string): TileRoom | null {
  return map.rooms.find((r) => r.id === id) ?? null
}

export function seatFor(room: TileRoom, characterId: string): TileSeat | null {
  return room.seats.find((s) => s.character === characterId) ?? null
}

/** Small stable string hash so each NPC wanders on its own schedule without randomness. */
function hash(text: string): number {
  let h = 0
  for (let i = 0; i < text.length; i++) h = (h * 31 + text.charCodeAt(i)) >>> 0
  return h
}

export interface NpcGoal {
  tile: Tile
  /** Direction to face on arrival (the seat's facing, otherwise keep the walking direction). */
  facing: LpcDirection | null
  /** True when the NPC is at its seat (sit / work animation applies), false while moving about the room. */
  atSeat: boolean
}

/**
 * Where an NPC should be for a behaviour. Deterministic: the same (behaviour, tick) always gives the same tile.
 *   working / idle / resting / celebration -> its seat      meeting -> the room's meeting tile
 *   emergency -> the room door                              walking -> a waypoint that changes every N ticks
 */
export function npcGoal(room: TileRoom, characterId: string, behavior: string, tick: number): NpcGoal {
  const seat = seatFor(room, characterId)
  const home: NpcGoal = seat
    ? { tile: seat.tile, facing: seat.facing, atSeat: true }
    : { tile: room.meet, facing: null, atSeat: false }
  switch (behavior) {
    case 'meeting':
      return { tile: room.meet, facing: null, atSeat: false }
    case 'emergency':
      return { tile: room.door, facing: null, atSeat: false }
    case 'walking': {
      if (room.wander.length === 0) return home
      const slot = Math.floor(Math.max(0, tick) / WORLD_CONFIG.tileWorld.wanderEveryTicks)
      return { tile: room.wander[(hash(characterId) + slot) % room.wander.length], facing: null, atSeat: false }
    }
    default:
      return home
  }
}

/** Id of the nearest character within `range` px of `p`, or null. Ties go to the lexicographically first id. */
export function nearestCharacter(characters: { id: string; x: number; y: number }[], p: Point, range: number): string | null {
  let best: string | null = null
  let bestD = Infinity
  for (const c of characters) {
    const d = Math.hypot(c.x - p.x, c.y - p.y)
    if (d <= range && (d < bestD || (d === bestD && best !== null && c.id < best))) {
      best = c.id
      bestD = d
    }
  }
  return best
}

/**
 * Advances along `waypoints` (px) by `speed * dtSeconds`. Returns the new position, the remaining waypoints and
 * the step actually taken (for facing). Never overshoots a waypoint.
 */
export function stepAlong(pos: Point, waypoints: Point[], speed: number, dtSeconds: number): { pos: Point; rest: Point[]; dx: number; dy: number } {
  let { x, y } = pos
  let budget = Math.max(0, speed * dtSeconds)
  let i = 0
  while (i < waypoints.length && budget > 0) {
    const dist = Math.hypot(waypoints[i].x - x, waypoints[i].y - y)
    if (dist <= budget) {
      x = waypoints[i].x
      y = waypoints[i].y
      budget -= dist
      i++
    } else {
      x += ((waypoints[i].x - x) / dist) * budget
      y += ((waypoints[i].y - y) / dist) * budget
      budget = 0
    }
  }
  return { pos: { x, y }, rest: waypoints.slice(i), dx: x - pos.x, dy: y - pos.y }
}

/** True when keyboard input belongs to a text field (chat box, search) and must not move the avatar. */
export function isTypingTarget(el: { tagName?: string; isContentEditable?: boolean } | null | undefined): boolean {
  if (!el) return false
  const tag = (el.tagName ?? '').toUpperCase()
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || el.isContentEditable === true
}

/** Keyboard state -> unit-speed movement vector (diagonals normalised so they are not faster). */
export function inputVector(keys: { up: boolean; down: boolean; left: boolean; right: boolean }): Point {
  const x = (keys.right ? 1 : 0) - (keys.left ? 1 : 0)
  const y = (keys.down ? 1 : 0) - (keys.up ? 1 : 0)
  if (x === 0 && y === 0) return { x: 0, y: 0 }
  const len = Math.hypot(x, y)
  return { x: x / len, y: y / len }
}

/** Avatar roles the player may pick: every LPC sheet, sorted, with the manifest default first. */
export function avatarChoices(sheetRoles: string[], defaultAvatar: string): string[] {
  const rest = [...sheetRoles].filter((r) => r !== defaultAvatar).sort()
  return sheetRoles.includes(defaultAvatar) ? [defaultAvatar, ...rest] : rest
}

/** A stored avatar if it is still a valid choice, otherwise the first choice. */
export function resolveAvatar(stored: string | null | undefined, choices: string[]): string {
  return stored && choices.includes(stored) ? stored : choices[0]
}

/**
 * LPC animation for a character that is standing still: the manifest's own behaviour table (V16 §93 — the LPC `sit`
 * rows are a floor-sit sequence, not a chair pose, so only `resting` sits; `working` stands at its desk). A
 * `walking` behaviour that has reached its waypoint just stands. Roles whose garment lacks the pose fall back.
 */
export function restingAnimation(
  lpc: Pick<LpcManifest, 'animations' | 'behaviorAnimation' | 'fallbackAnimation' | 'unsupportedAnimations'>,
  role: string,
  behavior: string,
): string {
  return lpcAnimationName(lpc as LpcManifest, role, behavior === 'walking' ? 'idle' : behavior)
}
