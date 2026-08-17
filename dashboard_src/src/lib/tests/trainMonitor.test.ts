import { describe, it, expect } from 'vitest'
import { computeRowsGrowth } from '../trainMonitor'

describe('computeRowsGrowth', () => {
  it('returns null before a baseline has been observed', () => {
    expect(computeRowsGrowth(null, 500)).toBeNull()
  })

  it('returns null while current is not yet a number (still loading)', () => {
    expect(computeRowsGrowth(500, undefined)).toBeNull()
    expect(computeRowsGrowth(500, null)).toBeNull()
  })

  it('returns 0 — a real, meaningful "no growth yet" — not null, once both are known', () => {
    expect(computeRowsGrowth(500, 500)).toBe(0)
  })

  it('returns positive growth once the dataset has grown', () => {
    expect(computeRowsGrowth(500, 512)).toBe(12)
  })

  it('does not clamp a negative delta — surfaces a shrinking dataset honestly rather than hiding it', () => {
    expect(computeRowsGrowth(500, 480)).toBe(-20)
  })
})
