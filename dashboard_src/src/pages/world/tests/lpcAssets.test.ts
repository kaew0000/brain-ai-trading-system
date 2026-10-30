// V16 §93 — pure-logic tests for the LPC character helpers plus a contract check of the real manifest.
import { describe, expect, it } from 'vitest'
import worldManifest from '../../../../public/assets/world/manifest.json'
import {
  hasLpcCharacter,
  lpcAnimationName,
  lpcDirectionFromDelta,
  lpcFrameIndex,
  lpcFrameRange,
  lpcRow,
  lpcStaticFrame,
  type LpcManifest,
} from '../lpcAssets'

const manifest = worldManifest as unknown as { npc: Record<string, string>; lpc: LpcManifest }
const lpc = manifest.lpc

describe('lpcAssets (real manifest contract)', () => {
  it('has an LPC sheet for every legacy NPC role except the not-yet-supplied player', () => {
    for (const role of Object.keys(manifest.npc)) {
      if (role === 'player') continue
      expect(hasLpcCharacter(lpc, role), role).toBe(true)
    }
  })

  it('maps every behaviour to a defined animation that fits inside the sheet', () => {
    for (const anim of Object.values(lpc.behaviorAnimation)) expect(lpc.animations[anim], anim).toBeDefined()
    expect(lpc.animations[lpc.fallbackAnimation]).toBeDefined()
    for (const [name, anim] of Object.entries(lpc.animations)) {
      const lastRow = anim.row + (anim.directional ? lpc.directions.length - 1 : 0)
      expect(lastRow, name).toBeLessThan(lpc.rows)
      expect(anim.startFrame + anim.frames, name).toBeLessThanOrEqual(lpc.columns)
    }
  })

  it('never lets a role with a missing garment use an unsupported animation', () => {
    for (const role of Object.keys(lpc.sheets)) {
      for (const behavior of Object.keys(lpc.behaviorAnimation)) {
        const name = lpcAnimationName(lpc, role, behavior)
        expect(lpc.unsupportedAnimations[role] ?? [], `${role}/${behavior}`).not.toContain(name)
      }
    }
  })

  it('keeps every fallback-able static frame on the sheet', () => {
    const max = lpc.columns * lpc.rows
    for (const role of Object.keys(lpc.sheets)) {
      for (const behavior of Object.keys(lpc.behaviorAnimation)) {
        const f = lpcStaticFrame(lpc, role, behavior)
        expect(f).toBeGreaterThanOrEqual(0)
        expect(f).toBeLessThan(max)
      }
    }
  })
})

describe('lpcAssets (helpers)', () => {
  it('derives facing from the dominant movement axis', () => {
    expect(lpcDirectionFromDelta(5, 1)).toBe('right')
    expect(lpcDirectionFromDelta(-5, 1)).toBe('left')
    expect(lpcDirectionFromDelta(1, 5)).toBe('down')
    expect(lpcDirectionFromDelta(1, -5)).toBe('up')
    expect(lpcDirectionFromDelta(0, 0, 'left')).toBe('left')
  })

  it('computes rows and frames from the manifest layout (walk: up,left,down,right from row 8)', () => {
    expect(lpcRow(lpc, 'walk', 'up')).toBe(8)
    expect(lpcRow(lpc, 'walk', 'down')).toBe(10)
    expect(lpcFrameIndex(lpc, 'walk', 'down', 0)).toBe(10 * lpc.columns + 1)
    expect(lpcFrameRange(lpc, 'walk', 'down')).toEqual({ start: 10 * lpc.columns + 1, end: 10 * lpc.columns + 8 })
    expect(lpcFrameIndex(lpc, 'walk', 'down', 8)).toBe(lpcFrameIndex(lpc, 'walk', 'down', 0)) // wraps
  })

  it('falls back to the standing frame for unsupported animations and unknown behaviours', () => {
    expect(lpcAnimationName(lpc, 'ceo', 'resting')).toBe('sit')
    expect(lpcAnimationName(lpc, 'risk_manager', 'resting')).toBe(lpc.fallbackAnimation)
    expect(lpcAnimationName(lpc, 'ceo', 'no-such-behavior')).toBe(lpc.fallbackAnimation)
  })

  it('is off when disabled or the role has no sheet', () => {
    expect(hasLpcCharacter(null, 'ceo')).toBe(false)
    expect(hasLpcCharacter({ ...lpc, enabled: false }, 'ceo')).toBe(false)
    expect(hasLpcCharacter(lpc, 'player')).toBe(false)
  })
})
