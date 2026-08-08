// dashboard_src/src/pages/world/tests/wsStatus.test.ts
// Phase W13-3
import { describe, expect, it } from 'vitest'
import { deriveWsStatus, WS_STATUS_CLASSNAME, WS_STATUS_LABEL } from '../wsStatus'

describe('deriveWsStatus', () => {
  it('maps OPEN to LIVE', () => {
    expect(deriveWsStatus('OPEN', false)).toBe('LIVE')
    expect(deriveWsStatus('OPEN', true)).toBe('LIVE')
  })

  it('maps CONNECTING after a previous connection to RECONNECTING', () => {
    expect(deriveWsStatus('CONNECTING', true)).toBe('RECONNECTING')
  })

  it('maps CONNECTING on the very first attempt to DISCONNECTED', () => {
    expect(deriveWsStatus('CONNECTING', false)).toBe('DISCONNECTED')
  })

  it('maps CLOSED to DISCONNECTED regardless of history', () => {
    expect(deriveWsStatus('CLOSED', true)).toBe('DISCONNECTED')
    expect(deriveWsStatus('CLOSED', false)).toBe('DISCONNECTED')
  })

  it('maps CLOSING to DISCONNECTED', () => {
    expect(deriveWsStatus('CLOSING', true)).toBe('DISCONNECTED')
  })

  it('maps NONE (never constructed) to DISCONNECTED', () => {
    expect(deriveWsStatus('NONE', false)).toBe('DISCONNECTED')
  })

  it('maps an unrecognized readyState to DISCONNECTED (fail safe, never LIVE)', () => {
    expect(deriveWsStatus('UNKNOWN', true)).toBe('DISCONNECTED')
  })

  it('every status has a label and a class name', () => {
    for (const status of ['LIVE', 'RECONNECTING', 'DISCONNECTED'] as const) {
      expect(WS_STATUS_LABEL[status]).toBeTypeOf('string')
      expect(WS_STATUS_CLASSNAME[status]).toBeTypeOf('string')
    }
  })
})
