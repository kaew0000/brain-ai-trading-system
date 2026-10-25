// V16 §82 — pure helpers behind the live Office scene and the System Pulse.
import { describe, it, expect } from 'vitest'
import { characterTweenOffset, frameSignature } from '../sceneMapping'
import { buildPulse, formatAge } from '../pulse'
import type { RenderFrame, TickerHealth, WorldStateSnapshot } from '../types'

function frame(overrides: Partial<RenderFrame> = {}, x = 100, y = 200, anim = 'idle'): RenderFrame {
  return {
    sceneId: 's',
    roomId: 'ceo-tower',
    sequence: 1,
    camera: { x: 0, y: 0, zoom: 1, focusMode: 'room' },
    viewport: { width: 720, height: 420, scale: 1 },
    commands: [
      { commandType: 'tile', entityId: 'floor', layer: 'floor', zOrder: 0, screenX: 0, screenY: 0, metadata: {} },
      { commandType: 'sprite', entityId: 'primus', layer: 'characters', zOrder: 5, screenX: x, screenY: y, metadata: { animationState: anim } },
    ],
    ...overrides,
  }
}

describe('frameSignature', () => {
  it('is identical for identical frames', () => {
    expect(frameSignature(frame())).toBe(frameSignature(frame()))
  })
  it('ignores sub-0.1px float noise', () => {
    expect(frameSignature(frame({}, 100.001, 200))).toBe(frameSignature(frame({}, 100, 200)))
  })
  it('changes when a character moves, changes pose, or the room changes', () => {
    const base = frameSignature(frame())
    expect(frameSignature(frame({}, 104.6, 200))).not.toBe(base)
    expect(frameSignature(frame({}, 100, 200, 'walking'))).not.toBe(base)
    expect(frameSignature(frame({ roomId: 'lobby' }))).not.toBe(base)
  })
  it('does not change when only the sequence number does', () => {
    expect(frameSignature(frame({ sequence: 99 }))).toBe(frameSignature(frame()))
  })
})

describe('characterTweenOffset', () => {
  it('returns the offset to start from the previously displayed position', () => {
    const offset = characterTweenOffset({ x: 100, y: 200 }, { x: 104.6, y: 196 }, 240)
    expect(offset?.dx).toBeCloseTo(-4.6, 6)
    expect(offset?.dy).toBeCloseTo(4, 6)
  })
  it('returns null with no previous position (first draw / new room)', () => {
    expect(characterTweenOffset(undefined, { x: 1, y: 1 }, 240)).toBeNull()
  })
  it('returns null when nothing moved', () => {
    expect(characterTweenOffset({ x: 10, y: 10 }, { x: 10.2, y: 10 }, 240)).toBeNull()
  })
  it('snaps (null) for a teleport larger than the snap distance', () => {
    expect(characterTweenOffset({ x: 0, y: 0 }, { x: 300, y: 0 }, 240)).toBeNull()
    expect(characterTweenOffset({ x: 0, y: 0 }, { x: 240, y: 0 }, 240)).not.toBeNull()
  })
})

const OPTS = { staleSeconds: 180, recentEvents: 3 }
const NOW = Date.parse('2026-10-25T10:00:00Z')

function state(overrides: Partial<WorldStateSnapshot> = {}): WorldStateSnapshot {
  return {
    engineStatus: 'idle',
    capturedAt: '2026-10-25T09:59:30Z',
    sequence: 1,
    missions: [],
    portfolioSummary: null,
    notifications: [],
    events: [],
    telemetry: [],
    orders: [],
    reconciliation: null,
    ...overrides,
  }
}
const item = (m: ReturnType<typeof buildPulse>, key: string) => m.items.find((i) => i.key === key)!

describe('buildPulse', () => {
  it('shows only the world clock (as unknown) before any data arrives', () => {
    const m = buildPulse(null, null, NOW, OPTS)
    expect(m.items.map((i) => i.key)).toEqual(['clock'])
    expect(item(m, 'clock').value).toBe('—')
  })

  it('never fabricates numbers: missing values render as a dash', () => {
    const m = buildPulse(state(), null, NOW, OPTS)
    for (const key of ['pnl', 'winRate', 'avgRr', 'drawdown', 'reconciliation', 'host']) {
      expect(item(m, key).value).toBe('—')
    }
    expect(item(m, 'orders').value).toBe('0')
  })

  it('formats real portfolio-summary values with the right scale and tone', () => {
    const m = buildPulse(
      state({ portfolioSummary: { dailyPnl: 12.345, floatingPnl: null, drawdown: 0.032, winRate: 0.625, avgRr: 1.5 } }),
      null, NOW, OPTS,
    )
    expect(item(m, 'pnl').value).toBe('+12.35')
    expect(item(m, 'pnl').tone).toBe('ok')
    expect(item(m, 'winRate').value).toBe('63%')
    expect(item(m, 'drawdown').value).toBe('3.2%')
    expect(item(m, 'avgRr').value).toBe('1.50')
  })

  it('marks a negative P&L bad and zero neutral', () => {
    const neg = buildPulse(state({ portfolioSummary: { dailyPnl: -3, floatingPnl: null, drawdown: null, winRate: null, avgRr: null } }), null, NOW, OPTS)
    expect(item(neg, 'pnl').value).toBe('-3.00')
    expect(item(neg, 'pnl').tone).toBe('bad')
    const zero = buildPulse(state({ portfolioSummary: { dailyPnl: 0, floatingPnl: null, drawdown: null, winRate: null, avgRr: null } }), null, NOW, OPTS)
    expect(item(zero, 'pnl').tone).toBe('muted')
  })

  it('flags a stale real-data snapshot', () => {
    const fresh = buildPulse(state({ capturedAt: '2026-10-25T09:59:50Z' }), null, NOW, OPTS)
    expect(fresh.stale).toBe(false)
    expect(item(fresh, 'data').value).toBe('10s ago')
    const old = buildPulse(state({ capturedAt: '2026-10-25T09:50:00Z' }), null, NOW, OPTS)
    expect(old.stale).toBe(true)
    expect(item(old, 'data').tone).toBe('bad')
    expect(item(old, 'data').value).toBe('10m ago')
  })

  it('handles an unparseable timestamp without crashing or flagging stale', () => {
    const m = buildPulse(state({ capturedAt: 'garbage' }), null, NOW, OPTS)
    expect(m.dataAgeSeconds).toBeNull()
    expect(m.stale).toBe(false)
    expect(item(m, 'data').value).toBe('—')
  })

  it('flags emergency engine states', () => {
    expect(item(buildPulse(state({ engineStatus: 'halted' }), null, NOW, OPTS), 'engine').tone).toBe('bad')
    expect(item(buildPulse(state({ engineStatus: 'recovering' }), null, NOW, OPTS), 'engine').tone).toBe('bad')
    expect(item(buildPulse(state({ engineStatus: 'running' }), null, NOW, OPTS), 'engine').tone).toBe('muted')
  })

  it('reports world-clock health for every ticker status', () => {
    const t = (status: TickerHealth['status'], extra: Partial<TickerHealth> = {}): TickerHealth => ({ status, running: status !== 'stopped', ...extra })
    expect(item(buildPulse(null, t('ok', { intervalSeconds: 2 }), NOW, OPTS), 'clock')).toMatchObject({ value: 'ok · 2s', tone: 'ok' })
    expect(item(buildPulse(null, t('degraded', { lastError: 'boom' }), NOW, OPTS), 'clock')).toMatchObject({ tone: 'warn', hint: 'boom' })
    expect(item(buildPulse(null, t('stalled'), NOW, OPTS), 'clock').tone).toBe('warn')
    expect(item(buildPulse(null, t('stopped'), NOW, OPTS), 'clock').tone).toBe('bad')
    expect(item(buildPulse(null, t('disabled'), NOW, OPTS), 'clock')).toMatchObject({ value: 'per trading cycle', tone: 'muted' })
  })

  it('summarises orders, reconciliation, missions, alerts and host load', () => {
    const m = buildPulse(
      state({
        orders: [{ symbol: 'BTCUSDT', state: 'OPEN' }, { symbol: 'ETHUSDT', state: null }],
        reconciliation: { lastRun: null, lastResult: 'clean', eventCount: 4, suppressedRepeatCount: 0 },
        missions: [{ missionId: 'a', status: 'active' }, { missionId: 'b', status: 'done' }],
        notifications: [
          { id: '1', timestamp: 't', message: 'x', severity: 'critical', read: false },
          { id: '2', timestamp: 't', message: 'y', severity: 'warning', read: false },
          { id: '3', timestamp: 't', message: 'z', severity: 'critical', read: true },
        ],
        telemetry: [{ name: 'cpu_percent', value: 41.6, unit: '%', district: '' }, { name: 'ram_percent', value: 63.2, unit: '%', district: '' }],
      }),
      null, NOW, OPTS,
    )
    expect(item(m, 'orders')).toMatchObject({ value: '2', hint: 'BTCUSDT:OPEN, ETHUSDT' })
    expect(item(m, 'reconciliation')).toMatchObject({ value: 'clean', hint: '4 event(s)' })
    expect(item(m, 'missions').value).toBe('1')
    expect(item(m, 'alerts')).toMatchObject({ value: '2', tone: 'bad', hint: '1 critical · 1 warning' })
    expect(item(m, 'host').value).toBe('42% / 63%')
  })

  it('lists the newest events first, capped, preferring the message', () => {
    const ev = (n: number, message = '') => ({
      id: `e${n}`, timestamp: `2026-10-25T09:5${n}:00Z`, type: `type${n}`, district: 'd', severity: 'info', agent: '', message,
    })
    const m = buildPulse(state({ events: [ev(1, 'one'), ev(4), ev(2, 'two'), ev(3, 'three')] }), null, NOW, OPTS)
    expect(m.recentEvents.map((e) => e.id)).toEqual(['e4', 'e3', 'e2'])
    expect(m.recentEvents[0]).toMatchObject({ time: '09:54:00', text: 'type4' })
    expect(m.recentEvents[1].text).toBe('three')
  })
})

describe('formatAge', () => {
  it('formats ranges and rejects bad input', () => {
    expect(formatAge(5)).toBe('5s ago')
    expect(formatAge(125)).toBe('2m ago')
    expect(formatAge(7300)).toBe('2h ago')
    expect(formatAge(null)).toBe('—')
    expect(formatAge(-1)).toBe('—')
    expect(formatAge(Number.NaN)).toBe('—')
  })
})
