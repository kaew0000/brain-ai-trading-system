// dashboard_src/src/pages/world/tests/workspace.test.ts
// Phase W12 — frontend tests for the workspace REST client, same style
// as world.test.ts's own worldApi tests (mocked fetch, no
// @testing-library/react dependency).
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import { workspaceApi } from '../workspaceApi'

// Auth plumbing is mocked so these tests exercise only this layer: the
// startup wait (whenAuthSettled) resolves immediately instead of via its
// real fallback timer, and getAuthHeaders is controllable per test.
const { authHeadersMock } = vi.hoisted(() => ({
  authHeadersMock: vi.fn((): Record<string, string> => ({})),
}))
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, getAuthHeaders: authHeadersMock, whenAuthSettled: () => Promise.resolve() }
})


describe('workspaceApi', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
    authHeadersMock.mockReset()
    authHeadersMock.mockReturnValue({})
    vi.stubGlobal('fetch', fetchMock)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  function mockOk(data: unknown) {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ok: true, data }),
    })
  }

  it('getLayout calls GET /api/workspace/layout', async () => {
    mockOk({ version: 1, panels: [], openPanelIds: [] })
    await workspaceApi.getLayout()
    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/layout', { headers: {} })
  })

  it('resizePanel posts width/height as query params', async () => {
    mockOk({ version: 1, panels: [], openPanelIds: [] })
    await workspaceApi.resizePanel('ops-dashboard', 400, 300)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workspace/layout/panels/ops-dashboard/resize?width=400&height=300',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('collapsePanel posts collapsed as a query param', async () => {
    mockOk({ version: 1, panels: [], openPanelIds: [] })
    await workspaceApi.collapsePanel('ops-dashboard', true)
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workspace/layout/panels/ops-dashboard/collapse?collapsed=true',
      expect.objectContaining({ method: 'POST' }),
    )
  })

  it('getAgentPanels calls GET /api/workspace/agents', async () => {
    mockOk([])
    await workspaceApi.getAgentPanels()
    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/agents', { headers: {} })
  })

  it('getNotifications includes category and unread_only when provided', async () => {
    mockOk([])
    await workspaceApi.getNotifications('alert', true)
    const calledUrl = fetchMock.mock.calls[0][0] as string
    expect(calledUrl).toContain('category=alert')
    expect(calledUrl).toContain('unread_only=true')
  })

  it('getNotifications omits params when not provided', async () => {
    mockOk([])
    await workspaceApi.getNotifications()
    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/notifications', { headers: {} })
  })

  it('search encodes the query and optional kinds', async () => {
    mockOk([])
    await workspaceApi.search('a b', ['room', 'character'])
    const calledUrl = fetchMock.mock.calls[0][0] as string
    expect(calledUrl).toContain('q=a+b')
    expect(calledUrl).toContain('kinds=room%2Ccharacter')
  })

  it('quickNav calls the quick-nav endpoint', async () => {
    mockOk([])
    await workspaceApi.quickNav('ceo')
    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/quick-nav?q=ceo', { headers: {} })
  })

  it('recordHistory posts kind as query param and payload as JSON body', async () => {
    mockOk({ entryId: 1, kind: 'selection', payload: {}, timestamp: 't' })
    await workspaceApi.recordHistory('selection', { roomId: 'ceo-tower' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workspace/history?kind=selection',
      expect.objectContaining({ method: 'POST', body: JSON.stringify({ roomId: 'ceo-tower' }) }),
    )
  })

  it('throws a descriptive error on a non-ok response', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) })
    await expect(workspaceApi.getLayout()).rejects.toThrow('GET /api/workspace/layout failed: 404')
  })

  it('GET attaches the Bearer token (regression: bare fetch always got 401)', async () => {
    authHeadersMock.mockReturnValue({ Authorization: 'Bearer tok-123' })
    mockOk({ version: 1, panels: [], openPanelIds: [] })
    await workspaceApi.getLayout()
    expect(fetchMock).toHaveBeenCalledWith('/api/workspace/layout', { headers: { Authorization: 'Bearer tok-123' } })
  })

  it('POST with a JSON body keeps Content-Type and adds the Bearer token', async () => {
    authHeadersMock.mockReturnValue({ Authorization: 'Bearer tok-123' })
    mockOk({ entryId: 1, kind: 'selection', payload: {}, timestamp: 't' })
    await workspaceApi.recordHistory('selection', { roomId: 'ceo-tower' })
    expect(fetchMock).toHaveBeenCalledWith(
      '/api/workspace/history?kind=selection',
      expect.objectContaining({
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Authorization: 'Bearer tok-123' },
      }),
    )
  })
})
