// V16 §94 — the World labels itself correctly in every execution mode and survives a missing/failed mode fetch.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const { getMode } = vi.hoisted(() => ({ getMode: vi.fn() }))
vi.mock('../api', () => ({ worldApi: { getMode } }))

import ModeBadge from '../components/ModeBadge'
import { describeMode } from '../modeBadge'

;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true

const ctx = (mode: string, lane: string | null, over: Record<string, unknown> = {}) => ({ mode, lane, laneScoped: true, realMoney: mode === 'live', ...over })
const flush = () => act(async () => { await Promise.resolve(); await Promise.resolve() })

describe('describeMode', () => {
  it.each([
    ['live', 'LIVE · real money', 'rose'],
    ['testnet', 'TESTNET', 'amber'],
    ['paper', 'PAPER', 'sky'],
    ['training', 'TRAINING', 'sky'],
  ])('labels %s mode', (mode, label, colour) => {
    const info = describeMode(ctx(mode, mode === 'live' || mode === 'testnet' ? 'LIVE' : 'TRAINING'))
    expect(info.label).toBe(label)
    expect(info.className).toContain(colour)
  })

  it('says which lane the figures come from, or that they are combined', () => {
    expect(describeMode(ctx('paper', 'TRAINING')).detail).toContain('TRAINING lane only')
    expect(describeMode(ctx('live', 'LIVE', { laneScoped: false })).detail).toContain('all lanes combined')
  })

  it('renders a neutral badge for an unknown mode or no data', () => {
    expect(describeMode(ctx('sandbox-x', null)).label).toBe('MODE SANDBOX-X')
    expect(describeMode(null).label).toBe('MODE ?')
    expect(describeMode(undefined).className).toContain('slate')
  })
})

describe('ModeBadge', () => {
  let container: HTMLDivElement
  let root: Root
  beforeEach(() => {
    vi.useFakeTimers()
    getMode.mockReset()
    container = document.createElement('div')
    root = createRoot(container)
  })
  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
  })

  it.each(['paper', 'testnet', 'live', 'training'])('shows the %s mode from the API', async (mode) => {
    getMode.mockResolvedValue(ctx(mode, 'LIVE'))
    await act(async () => { root.render(createElement(ModeBadge)) })
    await flush()
    const el = container.querySelector('[data-testid="world-mode-badge"]')!
    expect(el.getAttribute('data-mode')).toBe(mode)
  })

  it('stays neutral while loading and retries after a failed fetch', async () => {
    getMode.mockRejectedValueOnce(new Error('503')).mockResolvedValue(ctx('live', 'LIVE'))
    await act(async () => { root.render(createElement(ModeBadge)) })
    await flush()
    expect(container.querySelector('[data-testid="world-mode-badge"]')!.getAttribute('data-mode')).toBe('unknown')
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000) })
    await flush()
    expect(container.querySelector('[data-testid="world-mode-badge"]')!.getAttribute('data-mode')).toBe('live')
    expect(getMode).toHaveBeenCalledTimes(2)
  })

  it('stops retrying after unmount', async () => {
    getMode.mockRejectedValue(new Error('down'))
    await act(async () => { root.render(createElement(ModeBadge)) })
    await flush()
    act(() => root.unmount())
    await vi.advanceTimersByTimeAsync(60_000)
    expect(getMode).toHaveBeenCalledTimes(1)
    root = createRoot(container) // so afterEach can unmount cleanly
  })
})
