import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { api } from '../api'

/** Minimal stand-in for a fetch() Response — only the bits api.ts
 *  actually reads (.ok, .json()). Cast through `as Response` since
 *  this project's tsconfig has strict mode off (see dashboard_src/
 *  tsconfig.json) and a full Response mock adds nothing here. */
function jsonResponse(status: number, data: unknown): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => ({ ok: status < 300, data }),
  } as Response
}

// V16 Phase 4C — Dashboard Session Persistence. Covers restoreSession()
// and the updated logout() in lib/api.ts. api.ts's auth state (_authToken
// etc.) is module-level, not per-test, so every test starts from a known
// "logged out" baseline via the beforeEach below.
describe('api auth — V16 Phase 4C session persistence', () => {
  beforeEach(() => {
    // logout() fires a best-effort network call whenever there's an
    // existing session to revoke — stub fetch before using it purely
    // for cleanup, so a previous test's leftover session never leaks
    // into the next test's assertions (or throws for want of a mock).
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, { logged_out: true })))
    api.logout()
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  describe('restoreSession()', () => {
    it('returns true and populates auth state on a valid refresh cookie', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(
          jsonResponse(200, { token: 'tok-1', role: 'OPERATOR', expires_at: 1234567890, jti: 'jti-1' }),
        ),
      )

      const restored = await api.restoreSession()

      expect(restored).toBe(true)
      expect(api.authSnapshot()).toEqual({ authenticated: true, role: 'OPERATOR', expiresAt: 1234567890 })
    })

    it('returns false on a 401 (no/expired/revoked cookie) — never throws', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(401, null)))

      const restored = await api.restoreSession()

      expect(restored).toBe(false)
      expect(api.authSnapshot().authenticated).toBe(false)
    })

    it('returns false on a network error — never throws, never leaves a hung promise', async () => {
      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('network error')))

      await expect(api.restoreSession()).resolves.toBe(false)
      expect(api.authSnapshot().authenticated).toBe(false)
    })

    it('sends credentials: include, so the browser actually attaches the httpOnly cookie', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse(200, { token: 't', role: 'VIEWER', expires_at: 1, jti: 'j' }),
      )
      vi.stubGlobal('fetch', fetchMock)

      await api.restoreSession()

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/auth/session'),
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      )
    })

    it('a malformed 200 response (no token) is treated as "nothing to restore", not a crash', async () => {
      vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse(200, {})))

      const restored = await api.restoreSession()

      expect(restored).toBe(false)
    })
  })

  describe('logout()', () => {
    it('clears local auth state immediately, synchronously', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(jsonResponse(200, { token: 't', role: 'OPERATOR', expires_at: 1, jti: 'j' })),
      )
      await api.restoreSession()
      expect(api.authSnapshot().authenticated).toBe(true)

      api.logout()

      expect(api.authSnapshot()).toEqual({ authenticated: false, role: null, expiresAt: null })
    })

    it('calls POST /api/auth/logout with credentials when there was a session to revoke', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(jsonResponse(200, { token: 't', role: 'OPERATOR', expires_at: 1, jti: 'j' })),
      )
      await api.restoreSession()

      const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { logged_out: true }))
      vi.stubGlobal('fetch', fetchMock)

      api.logout()

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/auth/logout'),
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      )
    })

    it('does not call the network when there was no session to revoke', () => {
      // beforeEach already left auth state logged out.
      const fetchMock = vi.fn()
      vi.stubGlobal('fetch', fetchMock)

      api.logout()

      expect(fetchMock).not.toHaveBeenCalled()
    })

    it('never throws even if the best-effort revoke call fails', async () => {
      vi.stubGlobal(
        'fetch',
        vi.fn().mockResolvedValue(jsonResponse(200, { token: 't', role: 'OPERATOR', expires_at: 1, jti: 'j' })),
      )
      await api.restoreSession()

      vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')))

      expect(() => api.logout()).not.toThrow()
      expect(api.authSnapshot().authenticated).toBe(false) // local state cleared regardless of network outcome
    })
  })

  describe('login()', () => {
    it('sends credentials: include, so the server can set the httpOnly refresh cookie', async () => {
      const fetchMock = vi.fn().mockResolvedValue(
        jsonResponse(200, { token: 't', role: 'OPERATOR', expires_at: 1, jti: 'j' }),
      )
      vi.stubGlobal('fetch', fetchMock)

      await api.login('some-api-key')

      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining('/api/auth/token'),
        expect.objectContaining({ method: 'POST', credentials: 'include' }),
      )
    })
  })
})
