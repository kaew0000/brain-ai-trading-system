// dashboard_src/src/lib/tests/api.auth.test.ts
//
// V16 dashboard-auth-fix — coverage for the two bugs behind the endless
// `UNAUTHORIZED ... token expired` / `... missing credentials` WARNING
// spam logged by api/auth.py's log_unauthorized(): ManagedWS never
// carrying a token on the WS handshake, and the Bearer token never being
// refreshed before it expired.
//
// WebSocket is stubbed via vi.hoisted() so the fake is installed BEFORE
// '@/lib/api' is imported below — that module touches its WS singletons
// as an import-time side effect, and jsdom ships a real WebSocket that
// would otherwise attempt an actual network connection in this test.
import { describe, it, expect, beforeEach, vi } from 'vitest'

const { FakeWebSocket } = vi.hoisted(() => {
  class FakeWebSocket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSING = 2
    static CLOSED = 3
    static instances: FakeWebSocket[] = []
    readyState = FakeWebSocket.CONNECTING
    url: string
    onopen: (() => void) | null = null
    onclose: (() => void) | null = null
    onmessage: ((e: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    constructor(url: string) {
      this.url = url
      FakeWebSocket.instances.push(this)
    }
    close(): void {
      this.readyState = FakeWebSocket.CLOSED
      this.onclose?.()
    }
  }
  ;(globalThis as any).WebSocket = FakeWebSocket
  return { FakeWebSocket }
})

import { api, ManagedWS, wsEvents } from '@/lib/api'
import { useAuth } from '@/stores'

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

/** FastAPI's _ok() envelope (api/app.py) for successful auth responses:
 *  { ok: true, data: { token, role, expires_at, jti } }. */
function authOk(token: string, expiresAt: number, role = 'operator') {
  return jsonResponse(200, { ok: true, data: { token, role, expires_at: expiresAt, jti: `jti-${token}` } })
}

const NOW_S = 1_700_000_000

beforeEach(() => {
  api.logout()
  FakeWebSocket.instances.length = 0
  vi.stubGlobal('fetch', vi.fn())
  vi.useRealTimers()
})

describe('ManagedWS — no credentials, no handshake attempt', () => {
  it('does not open a socket while unauthenticated (the "missing credentials" loop this replaces)', () => {
    const ws = new ManagedWS('/ws/probe')
    ws.connect()
    expect(FakeWebSocket.instances.length).toBe(0)
    expect(ws.readyState).toBe('NONE')
  })

  it('appends the current bearer token as ?token=... once authenticated', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce(authOk('tok-abc', NOW_S + 3600))
    await api.login('some-api-key')

    // login() above also reconnects the module's own WS singletons (see
    // the next describe block) — find our own probe instance by URL
    // rather than assuming it's the only/first socket created.
    const ws = new ManagedWS('/ws/probe')
    ws.connect()
    const probe = FakeWebSocket.instances.find(i => i.url.includes('/ws/probe'))

    expect(probe).toBeDefined()
    expect(probe!.url).toMatch(/\?token=tok-abc$/)
  })
})

describe('module WS singletons react to login/logout', () => {
  it('reconnect the instant login succeeds', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce(authOk('tok-xyz', NOW_S + 3600))
    await api.login('some-api-key')

    expect(wsEvents.readyState).toBe('CONNECTING')
  })

  it('disconnect on logout', async () => {
    ;(globalThis.fetch as any).mockResolvedValueOnce(authOk('tok-xyz', NOW_S + 3600))
    await api.login('some-api-key')
    expect(wsEvents.readyState).toBe('CONNECTING')

    api.logout()
    expect(wsEvents.readyState).toBe('CLOSED')
  })
})

describe('proactive token rotation', () => {
  it('rotates before the token expires, keeping the session (and useAuth) alive', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW_S * 1000)

    ;(globalThis.fetch as any)
      .mockResolvedValueOnce(authOk('tok-1', NOW_S + 120)) // login: 2 min TTL
      .mockResolvedValueOnce(authOk('tok-2', NOW_S + 120 + 3600)) // rotate: fresh 1h TTL

    await api.login('some-api-key')
    expect(api.authSnapshot().expiresAt).toBe(NOW_S + 120)

    // ROTATE_MARGIN_S=60 → scheduled to fire 60s before the 120s expiry.
    await vi.advanceTimersByTimeAsync(60_000)

    expect(globalThis.fetch).toHaveBeenCalledWith(
      '/api/auth/rotate',
      expect.objectContaining({ method: 'POST' }),
    )
    expect(api.authSnapshot().authenticated).toBe(true)
    expect(api.authSnapshot().expiresAt).toBe(NOW_S + 120 + 3600)
    expect(useAuth.getState().expiresAt).toBe(NOW_S + 120 + 3600)

    vi.useRealTimers()
  })

  it('drops to a clean logged-out state if rotation fails, instead of retrying a dead token forever', async () => {
    vi.useFakeTimers()
    vi.setSystemTime(NOW_S * 1000)

    ;(globalThis.fetch as any)
      .mockResolvedValueOnce(authOk('tok-1', NOW_S + 120))
      .mockResolvedValueOnce(jsonResponse(401, { detail: 'token expired' }))

    await api.login('some-api-key')
    await vi.advanceTimersByTimeAsync(60_000)

    expect(api.authSnapshot().authenticated).toBe(false)
    expect(useAuth.getState().role).toBeNull()
    expect(useAuth.getState().error).toMatch(/session expired/i)
    // The WS channels must not be left retrying with a now-dead token —
    // that would just trade "token expired" (HTTP) for "token expired"
    // (WS) on the next reconnect attempt.
    expect(wsEvents.readyState).toBe('CLOSED')

    vi.useRealTimers()
  })
})
