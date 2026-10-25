// dashboard_src/src/lib/tests/api.authSettled.test.ts
//
// Startup-ordering fix: React runs child effects before the parent's, so the
// polling hooks fired their first request before Layout's restoreSession() /
// boot-token login finished -- a guaranteed 401 per endpoint on every page
// load. whenAuthSettled() lets callers wait for that first attempt.
//
// api.ts keeps this state at module level, so each test loads a fresh copy
// via vi.resetModules() + dynamic import. WebSocket is stubbed first because
// api.ts constructs its ManagedWS singletons at import time.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

vi.hoisted(() => {
  class FakeWebSocket {
    static CONNECTING = 0
    static OPEN = 1
    static CLOSING = 2
    static CLOSED = 3
    readyState = 0
    onopen: (() => void) | null = null
    onclose: (() => void) | null = null
    onmessage: ((e: { data: string }) => void) | null = null
    onerror: (() => void) | null = null
    close(): void {
      this.readyState = 3
    }
  }
  ;(globalThis as any).WebSocket = FakeWebSocket
})

function jsonResponse(status: number, body: unknown) {
  return { ok: status >= 200 && status < 300, status, json: async () => body }
}

const SESSION_OK = {
  ok: true,
  data: { token: 'tok-abc', role: 'OPERATOR', expires_at: Math.floor(Date.now() / 1000) + 3600 },
}

async function freshApi() {
  vi.resetModules()
  return await import('@/lib/api')
}

/** Flushes pending microtasks so promise continuations have run. */
const flush = () => Promise.resolve().then(() => Promise.resolve())

describe('whenAuthSettled / getAuthHeaders', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.useRealTimers()
    vi.unstubAllGlobals()
  })

  it('stays pending until restoreSession() finishes, then resolves', async () => {
    const mod = await freshApi()
    let release!: (v: unknown) => void
    fetchMock.mockReturnValueOnce(new Promise((res) => (release = res)))

    let settled = false
    mod.whenAuthSettled().then(() => (settled = true))
    const restoring = mod.api.restoreSession()
    await flush()
    expect(settled).toBe(false)

    release(jsonResponse(200, SESSION_OK))
    await restoring
    await flush()
    expect(settled).toBe(true)
  })

  it('exposes the token before waiters resume (first request is authenticated)', async () => {
    const mod = await freshApi()
    fetchMock.mockResolvedValueOnce(jsonResponse(200, SESSION_OK))
    const waiter = mod.whenAuthSettled().then(() => mod.getAuthHeaders())
    await mod.api.restoreSession()
    expect(await waiter).toEqual({ Authorization: 'Bearer tok-abc' })
  })

  it('resolves even when restoreSession() finds no session (401)', async () => {
    const mod = await freshApi()
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: 'no session' }))
    const waiter = mod.whenAuthSettled()
    expect(await mod.api.restoreSession()).toBe(false)
    await expect(waiter).resolves.toBeUndefined()
    expect(mod.getAuthHeaders()).toEqual({})
  })

  it('resolves even when restoreSession() hits a network error', async () => {
    const mod = await freshApi()
    fetchMock.mockRejectedValueOnce(new Error('offline'))
    const waiter = mod.whenAuthSettled()
    expect(await mod.api.restoreSession()).toBe(false)
    await expect(waiter).resolves.toBeUndefined()
  })

  it('resolves after a failed login() too', async () => {
    const mod = await freshApi()
    fetchMock.mockResolvedValueOnce(jsonResponse(401, { detail: 'invalid API key' }))
    const waiter = mod.whenAuthSettled()
    await expect(mod.api.login('wrong')).rejects.toThrow('invalid API key')
    await expect(waiter).resolves.toBeUndefined()
  })

  it('falls back to resolving when nothing ever signs in (never blocks forever)', async () => {
    vi.useFakeTimers()
    const mod = await freshApi()
    let settled = false
    mod.whenAuthSettled().then(() => (settled = true))
    await vi.advanceTimersByTimeAsync(1_000)
    expect(settled).toBe(false)
    await vi.advanceTimersByTimeAsync(600)
    expect(settled).toBe(true)
  })

  it('resolves immediately once already settled', async () => {
    const mod = await freshApi()
    fetchMock.mockResolvedValueOnce(jsonResponse(401, {}))
    await mod.api.restoreSession()
    await expect(mod.whenAuthSettled()).resolves.toBeUndefined()
  })

  it('getAuthHeaders is empty before sign-in', async () => {
    const mod = await freshApi()
    expect(mod.getAuthHeaders()).toEqual({})
  })
})
