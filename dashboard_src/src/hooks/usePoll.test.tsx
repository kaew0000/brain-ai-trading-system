// dashboard_src/src/hooks/usePoll.test.tsx
//
// usePoll must not fire its first request until the initial sign-in attempt
// has settled (otherwise every endpoint's first poll is a guaranteed 401 on
// page load), and must clean up correctly whether unmounted before or after.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createElement, act } from 'react'
import { createRoot, type Root } from 'react-dom/client'

const { gate } = vi.hoisted(() => {
  const g = { promise: Promise.resolve(), release: () => {} }
  return { gate: g }
})
vi.mock('@/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/lib/api')>()
  return { ...actual, whenAuthSettled: () => gate.promise }
})

import { usePoll } from './useData'

;(globalThis as any).IS_REACT_ACT_ENVIRONMENT = true

function Probe({ fn, ms, stop }: { fn: () => Promise<void>; ms: number; stop?: boolean }) {
  usePoll(fn, ms, stop)
  return null
}

describe('usePoll', () => {
  let container: HTMLDivElement
  let root: Root

  beforeEach(() => {
    vi.useFakeTimers()
    container = document.createElement('div')
    root = createRoot(container)
    gate.promise = new Promise<void>((res) => (gate.release = res))
  })

  afterEach(() => {
    act(() => root.unmount())
    vi.useRealTimers()
  })

  const settle = async () => {
    await act(async () => {
      gate.release()
      await Promise.resolve()
    })
  }

  it('does not poll before auth settles, then polls immediately and on the interval', async () => {
    const fn = vi.fn(async () => {})
    act(() => root.render(createElement(Probe, { fn, ms: 1000 })))
    expect(fn).not.toHaveBeenCalled()

    await vi.advanceTimersByTimeAsync(5000)
    expect(fn).not.toHaveBeenCalled() // still waiting on auth

    await settle()
    expect(fn).toHaveBeenCalledTimes(1)

    await vi.advanceTimersByTimeAsync(1000)
    expect(fn).toHaveBeenCalledTimes(2)
  })

  it('never polls when unmounted before auth settles', async () => {
    const fn = vi.fn(async () => {})
    act(() => root.render(createElement(Probe, { fn, ms: 1000 })))
    act(() => root.render(null))
    await settle()
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).not.toHaveBeenCalled()
  })

  it('stops polling after unmount', async () => {
    const fn = vi.fn(async () => {})
    act(() => root.render(createElement(Probe, { fn, ms: 1000 })))
    await settle()
    expect(fn).toHaveBeenCalledTimes(1)
    act(() => root.render(null))
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).toHaveBeenCalledTimes(1)
  })

  it('does nothing while stop is true', async () => {
    const fn = vi.fn(async () => {})
    act(() => root.render(createElement(Probe, { fn, ms: 1000, stop: true })))
    await settle()
    await vi.advanceTimersByTimeAsync(3000)
    expect(fn).not.toHaveBeenCalled()
  })
})
