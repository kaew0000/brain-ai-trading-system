// dashboard_src/src/lib/tests/bootToken.test.ts
import { describe, it, expect } from 'vitest'
import { parseBootToken } from '@/lib/bootToken'

describe('parseBootToken', () => {
  it('returns null token when there is no token param', () => {
    const result = parseBootToken('')
    expect(result.token).toBeNull()
    expect(result.strippedSearch).toBe('')
  })

  it('extracts a bare token param', () => {
    const result = parseBootToken('?token=abc123')
    expect(result.token).toBe('abc123')
    expect(result.strippedSearch).toBe('')
  })

  it('strips only the token param, preserving other params', () => {
    const result = parseBootToken('?token=abc123&foo=bar')
    expect(result.token).toBe('abc123')
    expect(result.strippedSearch).toBe('?foo=bar')
  })

  it('preserves other params when token is not first', () => {
    const result = parseBootToken('?foo=bar&token=abc123&baz=qux')
    expect(result.token).toBe('abc123')
    expect(result.strippedSearch).toBe('?foo=bar&baz=qux')
  })

  it('leaves unrelated search strings untouched when no token present', () => {
    const result = parseBootToken('?foo=bar&baz=qux')
    expect(result.token).toBeNull()
    expect(result.strippedSearch).toBe('?foo=bar&baz=qux')
  })

  it('treats an empty token value as present but empty, not absent', () => {
    // URLSearchParams.get returns '' (not null) for "?token=" — a
    // technically-present-but-empty token. Callers (Layout.tsx) only
    // act on truthy tokens, so this documents the boundary rather
    // than asserting a particular "correct" behavior here.
    const result = parseBootToken('?token=')
    expect(result.token).toBe('')
  })
})
