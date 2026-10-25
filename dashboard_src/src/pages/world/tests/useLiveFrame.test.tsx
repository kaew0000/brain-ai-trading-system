// V16 §82 — useLiveFrame: the selected room's frame must refresh on each
// world tick, never overwrite a newer frame with an older one, survive blips,
// and fall back to polling only while the socket is not LIVE.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import type { RenderFrame } from '../types'

const { getRoomFrame, wsState } = vi.hoisted(() => ({
  getRoomFrame: vi.fn(),
  wsState: { handler: null as ((m: unknown) => void) | null, unsubscribed: 0 },
}))
vi.mock('../api', () => ({
  worldApi: { getRoomFrame },
  wsWorld: {
    on: (h: (m: unknown) => void) => {
      wsState.handler = h
      return () => {
        wsState.unsubscribed += 1
        wsState.handler = null
      }
    },
  },
}))

import { useLiveFrame } from '../useLiveFrame'

;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true

const mkFrame = (roomId: string, seq: number): RenderFrame => ({
  sceneId: 's', roomId, sequence: seq,
  camera: { x: 0, y: 0, zoom: 1, focusMode: 'room' },
  viewport: { width: 1, height: 1, scale: 1 },
  commands: [],
})

let latest: RenderFrame | null = null
function Probe({ roomId, ws }: { roomId: string | null; ws: 'LIVE' | 'RECONNECTING' | 'DISCONNECTED' }) {
  latest = useLiveFrame(roomId, ws)
  return null
}

const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })
const emit = (type: string) => act(async () => { wsState.handler?.({ type }); await Promise.resolve() })

describe('useLiveFrame', () => {
  let root: Root
  beforeEach(() => {
    vi.useFakeTimers()
    getRoomFrame.mockReset()
    wsState.handler = null
    wsState.unsubscribed = 0
    latest = null
    root = createRoot(document.createElement('div'))
  })
  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
  })
  const render = (roomId: string | null, ws: 'LIVE' | 'RECONNECTING' | 'DISCONNECTED' = 'LIVE') =>
    act(() => root.render(createElement(Probe, { roomId, ws })))

  it('loads the frame when a room is selected and does nothing without one', async () => {
    getRoomFrame.mockResolvedValue(mkFrame('lobby', 1))
    render(null)
    await flush()
    expect(getRoomFrame).not.toHaveBeenCalled()
    render('lobby')
    await flush()
    expect(getRoomFrame).toHaveBeenCalledWith('lobby')
    expect(latest?.sequence).toBe(1)
  })

  it('refetches on every simulation tick message and on init, ignores other messages', async () => {
    getRoomFrame.mockResolvedValueOnce(mkFrame('lobby', 1)).mockResolvedValueOnce(mkFrame('lobby', 2)).mockResolvedValueOnce(mkFrame('lobby', 3))
    render('lobby')
    await flush()
    await emit('heartbeat')
    expect(getRoomFrame).toHaveBeenCalledTimes(1)
    await emit('simulation')
    await flush()
    expect(latest?.sequence).toBe(2)
    await emit('init')
    await flush()
    expect(latest?.sequence).toBe(3)
    expect(getRoomFrame).toHaveBeenCalledTimes(3)
  })

  it('keeps at most one refresh in flight', async () => {
    let release!: (f: RenderFrame) => void
    getRoomFrame.mockResolvedValueOnce(mkFrame('lobby', 1)).mockReturnValueOnce(new Promise<RenderFrame>((r) => (release = r)))
    render('lobby')
    await flush()
    await emit('simulation')
    await emit('simulation')
    await emit('simulation')
    expect(getRoomFrame).toHaveBeenCalledTimes(2) // initial + a single refresh
    release(mkFrame('lobby', 2))
    await flush()
    expect(latest?.sequence).toBe(2)
    getRoomFrame.mockResolvedValueOnce(mkFrame('lobby', 3))
    await emit('simulation')
    await flush()
    expect(latest?.sequence).toBe(3) // flag was released after the first refresh
  })

  it('drops a late response for a room that is no longer selected', async () => {
    let releaseOld!: (f: RenderFrame) => void
    getRoomFrame.mockReturnValueOnce(new Promise<RenderFrame>((r) => (releaseOld = r)))
    render('lobby')
    await flush()
    getRoomFrame.mockResolvedValueOnce(mkFrame('ceo-tower', 7))
    render('ceo-tower')
    await flush()
    expect(latest?.roomId).toBe('ceo-tower')
    releaseOld(mkFrame('lobby', 99))
    await flush()
    expect(latest?.roomId).toBe('ceo-tower') // stale lobby frame did not overwrite it
  })

  it('keeps the last good frame when a live refresh fails, but clears it when the room load fails', async () => {
    getRoomFrame.mockResolvedValueOnce(mkFrame('lobby', 1)).mockRejectedValueOnce(new Error('blip'))
    vi.spyOn(console, 'debug').mockImplementation(() => undefined)
    render('lobby')
    await flush()
    await emit('simulation')
    await flush()
    expect(latest?.sequence).toBe(1)
    getRoomFrame.mockRejectedValueOnce(new Error('gone'))
    render('ceo-tower')
    await flush()
    expect(latest).toBeNull()
  })

  it('polls as a fallback only while the socket is not LIVE', async () => {
    getRoomFrame.mockResolvedValue(mkFrame('lobby', 1))
    render('lobby', 'LIVE')
    await flush()
    getRoomFrame.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(getRoomFrame).not.toHaveBeenCalled()

    render('lobby', 'DISCONNECTED')
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(getRoomFrame).toHaveBeenCalledTimes(1)

    render('lobby', 'LIVE')
    getRoomFrame.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000) })
    expect(getRoomFrame).not.toHaveBeenCalled()
  })

  it('unsubscribes from the socket on unmount', async () => {
    getRoomFrame.mockResolvedValue(mkFrame('lobby', 1))
    render('lobby')
    await flush()
    act(() => root.unmount())
    expect(wsState.unsubscribed).toBeGreaterThanOrEqual(1)
    root = createRoot(document.createElement('div')) // keep afterEach's unmount valid
  })
})
