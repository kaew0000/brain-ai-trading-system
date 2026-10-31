// V16 §94 — pure-logic tests for the tile world plus contract checks of the real committed map and manifest.
import { describe, expect, it } from 'vitest'
import worldManifest from '../../../../public/assets/world/manifest.json'
import mapJson from '../../../../public/assets/world/tile/office.map.json'
import atlasJson from '../../../../public/assets/world/tile/atlas.json'
import { WORLD_CONFIG } from '../../../game/config/world.config'
import type { LpcManifest } from '../lpcAssets'
import {
  avatarChoices,
  canStandAt,
  findPath,
  footPoint,
  inputVector,
  isBlockedTile,
  isTypingTarget,
  moveWithCollision,
  nearestCharacter,
  npcGoal,
  parseTileMap,
  resolveAvatar,
  restingAnimation,
  roomAtTile,
  roomById,
  seatFor,
  stepAlong,
  tileOfFeet,
  type TileMap,
  type TileWorldManifest,
} from '../tileWorld'

const map: TileMap = parseTileMap(mapJson)
const manifest = worldManifest as unknown as { lpc: { sheets: Record<string, string> }; tileWorld: TileWorldManifest }

/** A tiny hand-made map: 5x4 room, wall ring, one pillar at (2,1), a seat at (1,1). */
function tinyMap(): TileMap {
  const rows = ['#####', '#...#', '#.#.#', '#####']
  return parseTileMap({
    version: 't', tileSize: 48, cols: 5, rows: 4, width: 240, height: 192,
    tiles: ['floor'], floor: rows.map((r) => [...r].map(() => 0)), collision: rows, props: [],
    rooms: [{ id: 'r', name: 'R', rect: [1, 1, 3, 2], door: [3, 1], meet: [3, 1], seats: [{ tile: [1, 1], facing: 'down', character: 'bob' }], wander: [[1, 1], [3, 1], [3, 2]] }],
    spawn: { tile: [1, 1], facing: 'down' },
  })
}

describe('parseTileMap', () => {
  it('accepts the committed map', () => {
    expect(map.cols).toBe(43)
    expect(map.rows).toBe(25)
    expect(map.collision).toHaveLength(map.rows)
  })

  it.each([
    ['not an object', null],
    ['bad collision row length', { ...mapJson, collision: mapJson.collision.map((r) => r.slice(1)) }],
    ['floor index out of range', { ...mapJson, floor: mapJson.floor.map((r) => r.map(() => 999)) }],
    ['bad spawn facing', { ...mapJson, spawn: { tile: [1, 1], facing: 'sideways' } }],
    ['bad seat facing', { ...mapJson, rooms: [{ ...mapJson.rooms[0], seats: [{ tile: [1, 1], facing: 'x', character: null }] }] }],
  ])('rejects %s', (_label, raw) => {
    expect(() => parseTileMap(raw)).toThrow(/invalid tile map/)
  })
})

describe('collision', () => {
  const t = tinyMap()

  it('treats walls, furniture and out-of-bounds as blocked', () => {
    expect(isBlockedTile(t, 0, 0)).toBe(true)
    expect(isBlockedTile(t, 2, 2)).toBe(true)
    expect(isBlockedTile(t, 1, 1)).toBe(false)
    expect(isBlockedTile(t, -1, 1)).toBe(true)
    expect(isBlockedTile(t, 1, 99)).toBe(true)
  })

  it('lets a character stand on a seat and keeps feet inside the seat tile', () => {
    const p = footPoint(t, [1, 1])
    expect(canStandAt(t, p)).toBe(true)
    expect(tileOfFeet(t, p)).toEqual([1, 1])
  })

  it('stops at a wall instead of passing through it', () => {
    let p = footPoint(t, [1, 1])
    for (let i = 0; i < 100; i++) p = moveWithCollision(t, p, -2, 0)
    expect(canStandAt(t, p)).toBe(true)
    expect(p.x).toBeGreaterThanOrEqual(48 + WORLD_CONFIG.tileWorld.hitboxHalfWidthPx)
  })

  it('slides along a wall: blocked on x, free on y', () => {
    const start = footPoint(t, [3, 1])
    const moved = moveWithCollision(t, { x: 3 * 48 + 48 - WORLD_CONFIG.tileWorld.hitboxHalfWidthPx - 0.5, y: start.y }, 5, 4)
    expect(moved.y).toBeGreaterThan(start.y) // y step taken
    expect(moved.x).toBeLessThan(4 * 48) // x step into the wall refused
  })

  it('never lets the player stand in a blocked tile of the real map after random walks', () => {
    let p = footPoint(map, map.spawn.tile)
    let seed = 7
    const rnd = () => (seed = (seed * 1664525 + 1013904223) >>> 0) / 2 ** 32
    for (let i = 0; i < 4000; i++) {
      p = moveWithCollision(map, p, (rnd() - 0.5) * 12, (rnd() - 0.5) * 12)
      expect(canStandAt(map, p)).toBe(true)
    }
  })
})

describe('findPath', () => {
  const t = tinyMap()

  it('routes around furniture', () => {
    const path = findPath(t, [1, 2], [3, 2])!
    expect(path[0]).toEqual([1, 2])
    expect(path[path.length - 1]).toEqual([3, 2])
    expect(path.some(([x, y]) => x === 2 && y === 2)).toBe(false)
    expect(path.length).toBe(5) // up, right, right, down... (1,2)->(1,1)->(2,1)->(3,1)->(3,2)
  })

  it('returns just the start when already there', () => {
    expect(findPath(t, [1, 1], [1, 1])).toEqual([[1, 1]])
  })

  it('walks up to a blocked target instead of failing', () => {
    const path = findPath(t, [1, 1], [2, 2])!
    const last = path[path.length - 1]
    expect(Math.abs(last[0] - 2) + Math.abs(last[1] - 2)).toBe(1)
    expect(isBlockedTile(t, last[0], last[1])).toBe(false)
  })

  it('returns null when the start itself is blocked', () => {
    expect(findPath(t, [0, 0], [1, 1])).toBeNull()
  })

  it('every step is to an adjacent walkable tile', () => {
    const path = findPath(map, map.spawn.tile, roomById(map, 'ceo-tower')!.seats[0].tile)!
    for (let i = 0; i < path.length; i++) {
      expect(isBlockedTile(map, path[i][0], path[i][1])).toBe(false)
      if (i) expect(Math.abs(path[i][0] - path[i - 1][0]) + Math.abs(path[i][1] - path[i - 1][1])).toBe(1)
    }
  })
})

describe('real map contract', () => {
  it('has a room for every backend room id (14 districts + lobby, hallway, elevator)', () => {
    const ids = map.rooms.map((r) => r.id).sort()
    expect(ids).toEqual([
      'ai-council', 'ceo-tower', 'command-hall', 'data-center', 'elevator', 'execution-forge', 'hallway',
      'journal-library', 'lobby', 'market-intelligence-center', 'portfolio-garden', 'recovery-center',
      'research-district', 'risk-fortress', 'simulation-lab', 'training-arena', 'world-gateway',
    ])
  })

  it('seats the 16 backend characters, each exactly once, on walkable tiles', () => {
    const seated = map.rooms.flatMap((r) => r.seats.filter((s) => s.character).map((s) => s.character as string))
    expect(seated.sort()).toEqual([
      'bastion', 'chameleon', 'chronos', 'crucible', 'echo', 'forge', 'gardener', 'herald',
      'mandelbrot', 'oracle', 'phoenix', 'primus', 'scribe', 'sentinel', 'watcher', 'webweaver',
    ])
    for (const r of map.rooms) for (const s of r.seats) expect(isBlockedTile(map, s.tile[0], s.tile[1]), `${r.id} seat`).toBe(false)
  })

  it('reaches every seat, meeting tile, door and wander tile from the spawn', () => {
    for (const r of map.rooms) {
      const targets = [r.meet, r.door, ...r.seats.map((s) => s.tile), ...r.wander]
      for (const tile of targets) {
        const path = findPath(map, map.spawn.tile, tile)!
        const last = path[path.length - 1]
        expect([last[0], last[1]], `${r.id} ${tile}`).toEqual(tile)
      }
    }
  })

  it('draws only sprites that exist in the atlas, and every floor tile name too', () => {
    const frames = new Set(Object.keys((atlasJson as { frames: Record<string, unknown> }).frames))
    for (const p of map.props) expect(frames.has(p.frame), p.frame).toBe(true)
    for (const name of map.tiles) expect(frames.has(name), name).toBe(true)
  })

  it('is enabled and fully described by the manifest', () => {
    expect(manifest.tileWorld.enabled).toBe(true)
    expect(manifest.tileWorld.defaultAvatar in manifest.lpc.sheets).toBe(true)
    for (const path of [manifest.tileWorld.map, manifest.tileWorld.atlas.image, manifest.tileWorld.atlas.data]) {
      expect(path.startsWith('/assets/world/tile/')).toBe(true)
    }
  })

  it('resolves rooms from tiles', () => {
    const ceo = roomById(map, 'ceo-tower')!
    expect(roomAtTile(map, ceo.seats[0].tile)?.id).toBe('ceo-tower')
    expect(roomAtTile(map, [0, 0])).toBeNull()
    expect(roomAtTile(map, map.spawn.tile)?.id).toBe('lobby')
  })
})

describe('npcGoal', () => {
  const t = tinyMap()
  const room = t.rooms[0]

  it('sends working / idle / resting / celebrating NPCs to their seat, facing as the seat does', () => {
    for (const b of ['working', 'idle', 'resting', 'celebration', 'unknown-future-behavior']) {
      expect(npcGoal(room, 'bob', b, 0)).toEqual({ tile: [1, 1], facing: 'down', atSeat: true })
    }
  })

  it('gathers a meeting at the meeting tile and sends an emergency to the door', () => {
    expect(npcGoal(room, 'bob', 'meeting', 0).tile).toEqual(room.meet)
    expect(npcGoal(room, 'bob', 'emergency', 0).tile).toEqual(room.door)
    expect(npcGoal(room, 'bob', 'meeting', 0).atSeat).toBe(false)
  })

  it('walks between waypoints on a schedule: stable within a window, changing across windows', () => {
    const n = WORLD_CONFIG.tileWorld.wanderEveryTicks
    expect(npcGoal(room, 'bob', 'walking', 0)).toEqual(npcGoal(room, 'bob', 'walking', n - 1))
    const tiles = new Set(Array.from({ length: room.wander.length }, (_, i) => npcGoal(room, 'bob', 'walking', i * n).tile.join(',')))
    expect(tiles.size).toBe(room.wander.length)
  })

  it('gives a seatless visitor the meeting tile instead of throwing', () => {
    expect(npcGoal(room, 'stranger', 'working', 0)).toEqual({ tile: room.meet, facing: null, atSeat: false })
    expect(seatFor(room, 'stranger')).toBeNull()
  })

  it('handles negative ticks (timeline seek) and an empty wander list', () => {
    expect(npcGoal(room, 'bob', 'walking', -5).tile).toBeDefined()
    expect(npcGoal({ ...room, wander: [] }, 'bob', 'walking', 3).atSeat).toBe(true)
  })
})

describe('interaction helpers', () => {
  it('picks the nearest character in range, none when out of range', () => {
    const chars = [{ id: 'a', x: 100, y: 100 }, { id: 'b', x: 130, y: 100 }]
    expect(nearestCharacter(chars, { x: 120, y: 100 }, 72)).toBe('b')
    expect(nearestCharacter(chars, { x: 500, y: 500 }, 72)).toBeNull()
    expect(nearestCharacter([], { x: 0, y: 0 }, 72)).toBeNull()
  })

  it('breaks distance ties on the lexicographically first id', () => {
    const chars = [{ id: 'b', x: 90, y: 100 }, { id: 'a', x: 110, y: 100 }]
    expect(nearestCharacter(chars, { x: 100, y: 100 }, 72)).toBe('a')
  })

  it('does not treat typing in a field as avatar input', () => {
    expect(isTypingTarget({ tagName: 'input' })).toBe(true)
    expect(isTypingTarget({ tagName: 'TEXTAREA' })).toBe(true)
    expect(isTypingTarget({ tagName: 'DIV', isContentEditable: true })).toBe(true)
    expect(isTypingTarget({ tagName: 'CANVAS' })).toBe(false)
    expect(isTypingTarget(null)).toBe(false)
  })

  it('normalises diagonal movement and cancels opposite keys', () => {
    const d = inputVector({ up: true, down: false, left: false, right: true })
    expect(Math.hypot(d.x, d.y)).toBeCloseTo(1)
    expect(inputVector({ up: true, down: true, left: false, right: false })).toEqual({ x: 0, y: 0 })
    expect(inputVector({ up: false, down: false, left: false, right: false })).toEqual({ x: 0, y: 0 })
  })
})

describe('stepAlong', () => {
  it('moves toward the waypoint without overshooting', () => {
    const r = stepAlong({ x: 0, y: 0 }, [{ x: 10, y: 0 }], 100, 1)
    expect(r.pos).toEqual({ x: 10, y: 0 })
    expect(r.rest).toEqual([])
  })

  it('carries leftover distance into the next waypoint', () => {
    const r = stepAlong({ x: 0, y: 0 }, [{ x: 10, y: 0 }, { x: 10, y: 20 }], 20, 1)
    expect(r.pos).toEqual({ x: 10, y: 10 })
    expect(r.rest).toEqual([{ x: 10, y: 20 }])
    expect(r.dy).toBe(10)
  })

  it('stands still with no waypoints or no time', () => {
    expect(stepAlong({ x: 5, y: 5 }, [], 100, 1).pos).toEqual({ x: 5, y: 5 })
    expect(stepAlong({ x: 5, y: 5 }, [{ x: 50, y: 5 }], 100, 0).pos).toEqual({ x: 5, y: 5 })
  })
})

describe('avatar choice', () => {
  const roles = Object.keys(manifest.lpc.sheets)

  it('offers every LPC sheet, default first', () => {
    const choices = avatarChoices(roles, manifest.tileWorld.defaultAvatar)
    expect(choices[0]).toBe(manifest.tileWorld.defaultAvatar)
    expect([...choices].sort()).toEqual([...roles].sort())
  })

  it('falls back to the first choice for a missing or stale stored avatar', () => {
    const choices = avatarChoices(roles, manifest.tileWorld.defaultAvatar)
    expect(resolveAvatar('trader', choices)).toBe('trader')
    expect(resolveAvatar('deleted_role', choices)).toBe(choices[0])
    expect(resolveAvatar(null, choices)).toBe(choices[0])
  })

  it('still works when the default is not a sheet', () => {
    expect(avatarChoices(['b', 'a'], 'zzz')).toEqual(['a', 'b'])
  })
})

describe('restingAnimation (real LPC manifest)', () => {
  const lpc = (worldManifest as unknown as { lpc: LpcManifest }).lpc

  it('follows the manifest behaviour table: only resting sits (LPC sit is a floor sit), working stands', () => {
    expect(restingAnimation(lpc, 'ceo', 'resting')).toBe('sit')
    expect(restingAnimation(lpc, 'ceo', 'working')).toBe('stand')
    expect(restingAnimation(lpc, 'ceo', 'meeting')).toBe('stand')
    expect(restingAnimation(lpc, 'ceo', 'emergency')).toBe('stand')
    expect(restingAnimation(lpc, 'ceo', 'celebration')).toBe('emote')
  })

  it('a walker that has stopped stands instead of freezing mid-stride', () => {
    expect(restingAnimation(lpc, 'ceo', 'walking')).toBe('stand')
  })

  it('falls back to standing for roles whose garment has no sit / emote pose', () => {
    expect(restingAnimation(lpc, 'risk_manager', 'resting')).toBe(lpc.fallbackAnimation)
    expect(restingAnimation(lpc, 'risk_manager', 'celebration')).toBe(lpc.fallbackAnimation)
  })

  it('treats an unknown future behaviour as the fallback animation', () => {
    expect(restingAnimation(lpc, 'ceo', 'levitating')).toBe(lpc.fallbackAnimation)
  })
})
