// dashboard_src/src/pages/world/tests/world.test.ts
// Phase W10 — frontend tests. Focused on the same two things the old
// (now-replaced) world.test.ts covered: pure display-mapping logic and
// the REST client, both testable in jsdom without a real browser/canvas
// or @testing-library/react (not a dependency of this project).
import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest'
import {
  ACTIVITY_COLORS,
  BEHAVIOR_COLORS,
  activityColorHex,
  activityLabel,
  assetDisplayName,
  behaviorColorHex,
  behaviorLabel,
} from '../sceneMapping'
import { worldApi } from '../api'

describe('sceneMapping', () => {
  it('has a color for every character behavior', () => {
    const behaviors = ['idle', 'walking', 'working', 'meeting', 'emergency', 'celebration', 'resting'] as const
    for (const b of behaviors) {
      expect(BEHAVIOR_COLORS[b]).toBeTypeOf('number')
    }
  })

  it('has a color for every room activity', () => {
    const activities = ['quiet', 'busy', 'meeting', 'alert', 'critical', 'celebration'] as const
    for (const a of activities) {
      expect(ACTIVITY_COLORS[a]).toBeTypeOf('number')
    }
  })

  it('formats behavior color as a 6-digit hex string', () => {
    expect(behaviorColorHex('working')).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('formats activity color as a 6-digit hex string', () => {
    expect(activityColorHex('critical')).toMatch(/^#[0-9a-f]{6}$/)
  })

  it('capitalizes behavior labels', () => {
    expect(behaviorLabel('working')).toBe('Working')
  })

  it('capitalizes activity labels', () => {
    expect(activityLabel('critical')).toBe('Critical')
  })

  it('extracts a clean display name from an asset id', () => {
    expect(assetDisplayName('furniture.meeting-table')).toBe('meeting table')
    expect(assetDisplayName('sprite.primus.working')).toBe('working')
  })

  it('returns empty string for an undefined asset id', () => {
    expect(assetDisplayName(undefined)).toBe('')
  })
})

describe('worldApi', () => {
  const fetchMock = vi.fn()

  beforeEach(() => {
    fetchMock.mockReset()
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

  it('listRooms calls GET /api/world/rooms', async () => {
    mockOk([{ roomId: 'ceo-tower', activity: 'quiet', occupantCount: 1 }])
    const rooms = await worldApi.listRooms()
    expect(fetchMock).toHaveBeenCalledWith('/api/world/rooms')
    expect(rooms).toHaveLength(1)
  })

  it('getRoom calls GET /api/world/rooms/:id', async () => {
    mockOk({ roomId: 'ceo-tower', activity: 'quiet', occupantCount: 0 })
    await worldApi.getRoom('ceo-tower')
    expect(fetchMock).toHaveBeenCalledWith('/api/world/rooms/ceo-tower')
  })

  it('select posts to /api/world/select/:kind/:id', async () => {
    mockOk({ kind: 'room', targetId: 'ceo-tower' })
    await worldApi.select('room', 'ceo-tower')
    expect(fetchMock).toHaveBeenCalledWith('/api/world/select/room/ceo-tower', { method: 'POST' })
  })

  it('timelineSeek posts with a tick query param', async () => {
    mockOk({ tick: { tickNumber: 5 } })
    await worldApi.timelineSeek(5)
    expect(fetchMock).toHaveBeenCalledWith('/api/world/timeline/seek?tick=5', { method: 'POST' })
  })

  it('throws a descriptive error on a non-ok response', async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 404, json: async () => ({}) })
    await expect(worldApi.getRoom('nope')).rejects.toThrow('GET /api/world/rooms/nope failed: 404')
  })

  it('getNotifications includes category when provided', async () => {
    mockOk([])
    await worldApi.getNotifications('alert')
    expect(fetchMock).toHaveBeenCalledWith('/api/world/notifications?category=alert')
  })

  it('getNotifications omits category when not provided', async () => {
    mockOk([])
    await worldApi.getNotifications()
    expect(fetchMock).toHaveBeenCalledWith('/api/world/notifications')
  })

  it('search encodes the query', async () => {
    mockOk([])
    await worldApi.search('a b')
    expect(fetchMock).toHaveBeenCalledWith('/api/world/search?q=a%20b')
  })
})
