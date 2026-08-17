import { describe, it, expect } from 'vitest'
import { lifecycleButtonSpec, lifecycleButtonInert } from '../lifecycleControl'

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

describe('lifecycleButtonInert', () => {
  it('unauthorized + unconfirmed state (the real-world default before login) stays clickable — this is the ONLY path to onRequireLogin()', () => {
    const spec = lifecycleButtonSpec(undefined) // disabled: true — the bug this guards against
    expect(lifecycleButtonInert(spec, /*authorized*/ false, /*pending*/ false)).toBe(false)
  })

  it('unauthorized + mid-transition state also stays clickable — auth takes priority over lifecycle disablement', () => {
    const spec = lifecycleButtonSpec('STARTING')
    expect(lifecycleButtonInert(spec, false, false)).toBe(false)
  })

  it('unauthorized but a request is already pending — still inert (rare, but never double-fire)', () => {
    const spec = lifecycleButtonSpec(undefined)
    expect(lifecycleButtonInert(spec, false, true)).toBe(true)
  })

  it('authorized + confirmed actionable state — clickable, unchanged from before this fix', () => {
    const spec = lifecycleButtonSpec('STOPPED')
    expect(lifecycleButtonInert(spec, true, false)).toBe(false)
  })

  it('authorized + unconfirmed/mid-transition state — still inert, unchanged safety guarantee', () => {
    expect(lifecycleButtonInert(lifecycleButtonSpec(undefined), true, false)).toBe(true)
    expect(lifecycleButtonInert(lifecycleButtonSpec('STARTING'), true, false)).toBe(true)
  })

  it('authorized + actionable state but a command is in flight — inert until it resolves', () => {
    const spec = lifecycleButtonSpec('STOPPED')
    expect(lifecycleButtonInert(spec, true, true)).toBe(true)
  })
})
