// V16 §82 — SystemPulse renders the real snapshot, degrades honestly, and polls.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const { getWorldState, getTicker } = vi.hoisted(() => ({ getWorldState: vi.fn(), getTicker: vi.fn() }))
vi.mock('../api', () => ({ worldApi: { getWorldState, getTicker } }))

import SystemPulse from '../components/SystemPulse'

;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true

const snapshot = (over: Record<string, unknown> = {}) => ({
  engineStatus: 'idle',
  capturedAt: new Date().toISOString(),
  sequence: 1,
  missions: [],
  portfolioSummary: { dailyPnl: 5.5, floatingPnl: null, drawdown: 0.01, winRate: 0.5, avgRr: 2 },
  notifications: [],
  events: [{ id: 'e1', timestamp: '2026-10-25T09:00:00Z', type: 'trade', district: 'd', severity: 'info', agent: '', message: 'Order filled' }],
  telemetry: [],
  orders: [],
  reconciliation: null,
  ...over,
})
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve(); await Promise.resolve() })

describe('SystemPulse', () => {
  let container: HTMLDivElement
  let root: Root
  beforeEach(() => {
    vi.useFakeTimers()
    getWorldState.mockReset()
    getTicker.mockReset()
    container = document.createElement('div')
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
  })
  const text = (id: string) => container.querySelector(`[data-testid="${id}"]`)?.textContent ?? null

  it('renders real values, the world clock and recent events', async () => {
    getWorldState.mockResolvedValue(snapshot())
    getTicker.mockResolvedValue({ status: 'ok', running: true, intervalSeconds: 2 })
    act(() => root.render(createElement(SystemPulse)))
    await flush()
    expect(text('pulse-pnl')).toContain('+5.50')
    expect(text('pulse-winRate')).toContain('50%')
    expect(text('pulse-clock')).toContain('ok · 2s')
    expect(text('pulse-events')).toContain('Order filled')
    expect(container.querySelector('[data-testid="system-pulse-error"]')).toBeNull()
  })

  it('shows an error note but still renders the clock when the state call fails', async () => {
    getWorldState.mockRejectedValue(new Error('GET /api/world/state failed: 401'))
    getTicker.mockResolvedValue({ status: 'degraded', running: true, lastError: 'boom' })
    act(() => root.render(createElement(SystemPulse)))
    await flush()
    expect(container.querySelector('[data-testid="system-pulse-error"]')).not.toBeNull()
    expect(text('pulse-clock')).toContain('degraded')
    expect(container.querySelector('[data-testid="pulse-pnl"]')).toBeNull() // no fabricated numbers
  })

  it('polls on its interval and clears the error once the backend recovers', async () => {
    getWorldState.mockRejectedValueOnce(new Error('down')).mockResolvedValue(snapshot())
    getTicker.mockResolvedValue({ status: 'ok', running: true, intervalSeconds: 2 })
    act(() => root.render(createElement(SystemPulse)))
    await flush()
    expect(container.querySelector('[data-testid="system-pulse-error"]')).not.toBeNull()
    await act(async () => { await vi.advanceTimersByTimeAsync(5_000) })
    expect(getWorldState).toHaveBeenCalledTimes(2)
    expect(container.querySelector('[data-testid="system-pulse-error"]')).toBeNull()
    expect(text('pulse-pnl')).toContain('+5.50')
  })

  it('stops polling after unmount', async () => {
    getWorldState.mockResolvedValue(snapshot())
    getTicker.mockResolvedValue({ status: 'ok', running: true })
    act(() => root.render(createElement(SystemPulse)))
    await flush()
    act(() => root.render(null))
    getWorldState.mockClear()
    await act(async () => { await vi.advanceTimersByTimeAsync(30_000) })
    expect(getWorldState).not.toHaveBeenCalled()
  })
})
