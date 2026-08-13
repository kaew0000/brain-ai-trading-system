import { describe, it, expect } from 'vitest'
import { hasRole, ROLE_ORDER } from '../roles'

describe('hasRole', () => {
  it('exact role match satisfies itself', () => {
    expect(hasRole('OPERATOR', 'OPERATOR')).toBe(true)
  })

  it('higher role satisfies a lower requirement', () => {
    expect(hasRole('ADMIN', 'OPERATOR')).toBe(true)
    expect(hasRole('ADMIN', 'VIEWER')).toBe(true)
  })

  it('lower role does not satisfy a higher requirement', () => {
    expect(hasRole('VIEWER', 'OPERATOR')).toBe(false)
    expect(hasRole('OPERATOR', 'ADMIN')).toBe(false)
  })

  it('is case-insensitive', () => {
    expect(hasRole('operator', 'OPERATOR')).toBe(true)
  })

  it('null/undefined/unknown role fails closed', () => {
    expect(hasRole(null, 'VIEWER')).toBe(false)
    expect(hasRole(undefined, 'VIEWER')).toBe(false)
    expect(hasRole('NOT_A_ROLE', 'VIEWER')).toBe(false)
  })

  it('ROLE_ORDER stays in lockstep with api/auth.py Role(IntEnum): VIEWER=1,OPERATOR=2,ADMIN=3', () => {
    expect(ROLE_ORDER).toEqual(['VIEWER', 'OPERATOR', 'ADMIN'])
  })
})
