// Phase W-ISO-2 — pure-logic tests for the isometric asset helpers, plus a
// contract check of the real generated manifest (no Phaser/canvas needed).
import { describe, expect, it } from 'vitest'
import worldManifest from '../../../../public/assets/world/manifest.json'
import {
  hasIsoCharacter,
  isoDirectionFromDelta,
  isoPoseFrame,
  isoPoseName,
  isoPropDepthOffset,
  isoPropOrigin,
  isoTilePath,
  isoWalkFrame,
  resolveIsoProp,
  type IsoManifest,
} from '../isoAssets'

const iso = (worldManifest as unknown as { iso: IsoManifest }).iso

describe('isoAssets (generated manifest contract)', () => {
  it('ships an iso block with every pose the behaviour map can ask for', () => {
    const poses = new Set(iso.character.poses)
    for (const pose of Object.values(iso.character.behaviorPose)) expect(poses.has(pose)).toBe(true)
    expect(poses.has(iso.character.seatedWorkingPose)).toBe(true)
  })

  it('covers all seven simulation behaviours', () => {
    for (const b of ['idle', 'walking', 'working', 'meeting', 'emergency', 'celebration', 'resting']) {
      expect(iso.character.behaviorPose[b]).toBeTruthy()
    }
  })

  it('declares anchor/footprint/height for every prop (data, not constants)', () => {
    for (const [key, e] of Object.entries(iso.props)) {
      expect(e.anchor[0]).toBeGreaterThan(0)
      expect(e.anchor[0]).toBeLessThan(1)
      expect(e.anchor[1]).toBeGreaterThan(0)
      expect(e.anchor[1]).toBeLessThan(1)
      expect(e.footprint.length).toBe(2)
      expect(e.heightPx).toBeGreaterThan(0)
      expect(e.path).toContain(key)
    }
  })

  it('every asset id points at a declared prop', () => {
    for (const key of Object.values(iso.assetIds)) expect(iso.props[key]).toBeDefined()
  })

  it('has a pose sheet for all 16 characters', () => {
    expect(Object.keys(iso.npc).length).toBe(16)
  })
})

describe('isoAssets helpers', () => {
  it('resolves backend asset ids and returns null for unmapped ones', () => {
    expect(resolveIsoProp(iso, 'furniture.desk')?.key).toBe('desk')
    expect(resolveIsoProp(iso, 'furniture.partition-full')?.key).toBe('partition_full')
    expect(resolveIsoProp(iso, 'furniture.door')).toBeNull()
    expect(resolveIsoProp(iso, undefined)).toBeNull()
    expect(resolveIsoProp(null, 'furniture.desk')).toBeNull()
  })

  it('uses the seated pose only for working', () => {
    const c = iso.character
    expect(isoPoseName(c, 'working', true)).toBe(c.seatedWorkingPose)
    expect(isoPoseName(c, 'working', false)).toBe(c.behaviorPose.working)
    expect(isoPoseName(c, 'meeting', true)).toBe(c.behaviorPose.meeting)
    expect(isoPoseName(c, 'resting', true)).toBe(c.behaviorPose.resting)
  })

  it('falls back to idle pose for an unknown behaviour and frame 0 for an unknown pose', () => {
    expect(isoPoseName(iso.character, 'dancing', false)).toBe(iso.character.behaviorPose.idle)
    expect(isoPoseFrame(iso.character, 'nope')).toBe(0)
    expect(isoPoseFrame(iso.character, iso.character.seatedWorkingPose)).toBe(iso.character.poses.indexOf(iso.character.seatedWorkingPose))
  })

  it('derives origin and depth offset from the manifest entry', () => {
    const desk = iso.props.desk
    expect(isoPropOrigin(desk)).toEqual(desk.anchor)
    expect(isoPropDepthOffset(iso, desk)).toBe((desk.footprint[1] / 2) * iso.tile.height)
  })

  it('knows which characters have iso sheets', () => {
    expect(hasIsoCharacter(iso, 'primus')).toBe(true)
    expect(hasIsoCharacter(iso, 'nobody')).toBe(false)
    expect(hasIsoCharacter(null, 'primus')).toBe(false)
  })
})

describe('isoAssets W-ISO-3 (walk sheets + floor tiles)', () => {
  it('maps screen movement to the four iso facings', () => {
    expect(isoDirectionFromDelta(3, 2)).toBe('se')
    expect(isoDirectionFromDelta(-3, 2)).toBe('sw')
    expect(isoDirectionFromDelta(-3, -2)).toBe('nw')
    expect(isoDirectionFromDelta(3, -2)).toBe('ne')
    expect(isoDirectionFromDelta(0, 0, 'nw')).toBe('nw')
  })

  it('cycles walk frames from elapsed time and picks the direction row', () => {
    const id = Object.keys(iso.walk!.sheets)[0]
    const a = isoWalkFrame(iso, id, 'nw', 0)!
    expect(a.row).toBe(iso.walk!.directions.indexOf('nw'))
    expect(a.col).toBe(0)
    const b = isoWalkFrame(iso, id, 'nw', (1000 / iso.walk!.fps) * 1.1)!
    expect(b.col).toBe(1)
    const wrap = isoWalkFrame(iso, id, 'se', (1000 / iso.walk!.fps) * iso.walk!.frames)!
    expect(wrap.col).toBe(0)
  })

  it('returns null for unknown characters or manifests without walk data', () => {
    expect(isoWalkFrame(iso, 'nobody', 'se', 0)).toBeNull()
    expect(isoWalkFrame(null, 'primus', 'se', 0)).toBeNull()
    expect(isoTilePath({ ...iso, tiles: undefined }, 'floor_light')).toBeNull()
  })

  it('exposes the generated floor tiles', () => {
    expect(isoTilePath(iso, 'floor_light')).toMatch(/floor_light\.png$/)
  })
})
