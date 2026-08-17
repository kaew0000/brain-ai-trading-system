import { describe, it, expect } from 'vitest'
import { lifecycleButtonSpec, lifecycleButtonDisplay } from '../lifecycleControl'

describe('lifecycleButtonDisplay', () => {
  it('unauthorized + unconfirmed state (the real-world default before login) shows LOGIN, not the muted "…" — this is the bug fix', () => {
    const spec = lifecycleButtonSpec(undefined)
    const d = lifecycleButtonDisplay(spec, /*authorized*/ false, /*pending*/ false)
    expect(d.label).toBe('LOGIN')
    expect(d.tone).toBe('login')
  })

  it('unauthorized + any confirmed lifecycle state still shows LOGIN — spec is irrelevant until authorized', () => {
    for (const state of ['STOPPED', 'RUNNING', 'FAILED', 'STARTING', 'STOPPING'] as const) {
      const d = lifecycleButtonDisplay(lifecycleButtonSpec(state), false, false)
      expect(d.label).toBe('LOGIN')
      expect(d.tone).toBe('login')
    }
  })

  it('unauthorized + pending is still LOGIN — pending only ever applies to an authorized in-flight command', () => {
    const d = lifecycleButtonDisplay(lifecycleButtonSpec(undefined), false, true)
    expect(d.label).toBe('LOGIN')
    expect(d.tone).toBe('login')
  })

  it('authorized + confirmed actionable state — unchanged from spec, byte-for-byte', () => {
    const spec = lifecycleButtonSpec('STOPPED')
    const d = lifecycleButtonDisplay(spec, true, false)
    expect(d.label).toBe('START')
    expect(d.tone).toBe('stopped')
  })

  it('authorized + RUNNING — unchanged from spec', () => {
    const spec = lifecycleButtonSpec('RUNNING')
    const d = lifecycleButtonDisplay(spec, true, false)
    expect(d.label).toBe('STOP')
    expect(d.tone).toBe('running')
  })

  it('authorized + command in flight — shows the pending ellipsis, same as before this fix', () => {
    const spec = lifecycleButtonSpec('STOPPED')
    const d = lifecycleButtonDisplay(spec, true, true)
    expect(d.label).toBe('…')
    expect(d.tone).toBe('stopped')
  })

  it('authorized + unconfirmed/mid-transition state — unchanged muted "…" treatment', () => {
    const d = lifecycleButtonDisplay(lifecycleButtonSpec(undefined), true, false)
    expect(d.label).toBe('…')
    expect(d.tone).toBe('transitioning')
  })
})
