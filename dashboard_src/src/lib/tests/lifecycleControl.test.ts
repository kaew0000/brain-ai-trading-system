import { describe, it, expect } from 'vitest'
import { lifecycleButtonSpec } from '../lifecycleControl'

describe('lifecycleButtonSpec', () => {
  it('STOPPED offers START, enabled', () => {
    const s = lifecycleButtonSpec('STOPPED')
    expect(s.command).toBe('start bot')
    expect(s.disabled).toBe(false)
    expect(s.label).toBe('START')
  })

  it('RUNNING offers STOP, enabled', () => {
    const s = lifecycleButtonSpec('RUNNING')
    expect(s.command).toBe('stop bot')
    expect(s.disabled).toBe(false)
    expect(s.label).toBe('STOP')
  })

  it('FAILED offers a restart (start bot), enabled', () => {
    const s = lifecycleButtonSpec('FAILED')
    expect(s.command).toBe('start bot')
    expect(s.disabled).toBe(false)
    expect(s.tone).toBe('failed')
  })

  it('STARTING and STOPPING are disabled with no command — no optimistic action offered mid-transition', () => {
    for (const state of ['STARTING', 'STOPPING'] as const) {
      const s = lifecycleButtonSpec(state)
      expect(s.command).toBeNull()
      expect(s.disabled).toBe(true)
    }
  })

  it('unknown/undefined state is disabled — never guesses a transition against an unconfirmed state', () => {
    expect(lifecycleButtonSpec(undefined).disabled).toBe(true)
    expect(lifecycleButtonSpec(undefined).command).toBeNull()
  })
})
