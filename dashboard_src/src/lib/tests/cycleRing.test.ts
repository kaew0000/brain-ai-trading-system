import { describe, it, expect } from 'vitest'
import { computeCycleProgress } from '../cycleRing'

const NOW = Date.parse('2026-08-30T12:00:00.000Z')

describe('computeCycleProgress', () => {
  it('returns null when the lane is not running', () => {
    expect(computeCycleProgress(NOW, '2026-08-30T11:59:50.000Z', 20, false)).toBeNull()
  })

  it('returns null when no cycle has been observed yet', () => {
    expect(computeCycleProgress(NOW, null, 20, true)).toBeNull()
    expect(computeCycleProgress(NOW, undefined, 20, true)).toBeNull()
  })

  it('returns null when poll_interval_seconds is missing or non-positive', () => {
    expect(computeCycleProgress(NOW, '2026-08-30T11:59:50.000Z', undefined, true)).toBeNull()
    expect(computeCycleProgress(NOW, '2026-08-30T11:59:50.000Z', 0, true)).toBeNull()
  })

  it('returns null for an unparseable timestamp rather than guessing', () => {
    expect(computeCycleProgress(NOW, 'not-a-timestamp', 20, true)).toBeNull()
  })

  it('reads as just-started right after a cycle ticks', () => {
    const result = computeCycleProgress(NOW, '2026-08-30T12:00:00.000Z', 20, true)
    expect(result?.fraction).toBe(0)
    expect(result?.remainingSeconds).toBe(20)
  })

  it('reads as halfway through partway into the interval', () => {
    const result = computeCycleProgress(NOW, '2026-08-30T11:59:50.000Z', 20, true) // 10s elapsed of 20s
    expect(result?.fraction).toBeCloseTo(0.5, 5)
    expect(result?.remainingSeconds).toBe(10)
  })

  it('clamps fraction at 1 and remainingSeconds at 0 when a cycle is overdue', () => {
    const result = computeCycleProgress(NOW, '2026-08-30T11:59:00.000Z', 20, true) // 60s elapsed of 20s
    expect(result?.fraction).toBe(1)
    expect(result?.remainingSeconds).toBe(0)
  })
})
