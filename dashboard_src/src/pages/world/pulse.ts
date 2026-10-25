// dashboard_src/src/pages/world/pulse.ts
// V16 §82 — pure model for the System Pulse strip: turns the real
// /api/world/state snapshot (+ /api/world/ticker) into display rows.
//
// Honesty rules: a value the backend did not provide renders as "—", never a
// made-up zero. The numbers are exactly what world.runtime exposes: today's
// P&L / win rate / avg R:R come from the trade journal across ALL execution
// lanes (live + paper-training), which is why the labels say so. Open exchange
// positions are not exported to the World (no verified read-only accessor), so
// they are deliberately not shown here.
import type { TickerHealth, WorldStateSnapshot } from './types'

export type PulseTone = 'ok' | 'warn' | 'bad' | 'muted'

export interface PulseItem {
  key: string
  label: string
  value: string
  tone: PulseTone
  hint?: string
}

export interface PulseEvent {
  id: string
  time: string
  severity: string
  text: string
}

export interface PulseModel {
  items: PulseItem[]
  recentEvents: PulseEvent[]
  dataAgeSeconds: number | null
  stale: boolean
}

export interface PulseOptions {
  staleSeconds: number
  recentEvents: number
}

const DASH = '—'
// Mirrors world/workspace/operations_dashboard.py::_EMERGENCY_STATUSES.
const EMERGENCY_ENGINE_STATUSES = new Set(['halted', 'recovering'])

export function formatAge(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds) || seconds < 0) return DASH
  if (seconds < 60) return `${Math.round(seconds)}s ago`
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`
  return `${Math.floor(seconds / 3600)}h ago`
}

function signed(n: number | null | undefined, digits = 2): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return DASH
  return `${n > 0 ? '+' : ''}${n.toFixed(digits)}`
}

function percent(fraction: number | null | undefined, digits = 1): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return DASH
  return `${(fraction * 100).toFixed(digits)}%`
}

function pnlTone(n: number | null | undefined): PulseTone {
  if (n === null || n === undefined || !Number.isFinite(n) || n === 0) return 'muted'
  return n > 0 ? 'ok' : 'bad'
}

function telemetryValue(state: WorldStateSnapshot, name: string): number | null {
  const row = state.telemetry.find((t) => t.name === name)
  return row && Number.isFinite(row.value) ? row.value : null
}

function clockTime(iso: string): string {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return DASH
  return d.toISOString().slice(11, 19)
}

function clockItem(ticker: TickerHealth | null): PulseItem {
  if (!ticker) return { key: 'clock', label: 'World clock', value: DASH, tone: 'muted' }
  const interval = ticker.intervalSeconds ? ` · ${ticker.intervalSeconds}s` : ''
  switch (ticker.status) {
    case 'ok':
      return { key: 'clock', label: 'World clock', value: `ok${interval}`, tone: 'ok' }
    case 'degraded':
      return { key: 'clock', label: 'World clock', value: 'degraded', tone: 'warn', hint: ticker.lastError ?? undefined }
    case 'stalled':
      return { key: 'clock', label: 'World clock', value: 'stalled', tone: 'warn', hint: 'No tick for several intervals' }
    case 'stopped':
      return { key: 'clock', label: 'World clock', value: 'stopped', tone: 'bad' }
    default:
      return { key: 'clock', label: 'World clock', value: 'per trading cycle', tone: 'muted', hint: 'Dedicated ticker disabled' }
  }
}

export function buildPulse(
  state: WorldStateSnapshot | null,
  ticker: TickerHealth | null,
  nowMs: number,
  options: PulseOptions,
): PulseModel {
  const items: PulseItem[] = [clockItem(ticker)]

  if (!state) {
    return { items, recentEvents: [], dataAgeSeconds: null, stale: false }
  }

  const capturedMs = Date.parse(state.capturedAt)
  const dataAgeSeconds = Number.isNaN(capturedMs) ? null : Math.max(0, (nowMs - capturedMs) / 1000)
  const stale = dataAgeSeconds !== null && dataAgeSeconds > options.staleSeconds

  items.push({
    key: 'engine',
    label: 'Engine',
    value: state.engineStatus || DASH,
    tone: EMERGENCY_ENGINE_STATUSES.has(state.engineStatus) ? 'bad' : 'muted',
  })
  items.push({
    key: 'data',
    label: 'Data snapshot',
    value: formatAge(dataAgeSeconds),
    tone: stale ? 'bad' : dataAgeSeconds === null ? 'muted' : 'ok',
    hint: stale ? 'Real-data export looks stale' : undefined,
  })

  const summary = state.portfolioSummary
  items.push({ key: 'pnl', label: 'Today P&L (all lanes)', value: signed(summary?.dailyPnl), tone: pnlTone(summary?.dailyPnl) })
  items.push({ key: 'winRate', label: 'Win rate (today)', value: percent(summary?.winRate, 0), tone: 'muted' })
  items.push({
    key: 'avgRr',
    label: 'Avg R:R (today)',
    value: summary?.avgRr === null || summary?.avgRr === undefined ? DASH : summary.avgRr.toFixed(2),
    tone: 'muted',
  })
  items.push({ key: 'drawdown', label: 'Drawdown', value: percent(summary?.drawdown), tone: 'muted' })

  items.push({
    key: 'orders',
    label: 'Active orders',
    value: String(state.orders.length),
    tone: 'muted',
    hint: state.orders.slice(0, 4).map((o) => `${o.symbol}${o.state ? `:${o.state}` : ''}`).join(', ') || undefined,
  })
  const rec = state.reconciliation
  items.push({
    key: 'reconciliation',
    label: 'Reconciliation',
    value: rec?.lastResult ?? DASH,
    tone: 'muted',
    hint: rec?.eventCount !== null && rec?.eventCount !== undefined ? `${rec.eventCount} event(s)` : undefined,
  })
  items.push({
    key: 'missions',
    label: 'Active missions',
    value: String(state.missions.filter((m) => m.status === 'active').length),
    tone: 'muted',
  })

  const unread = state.notifications.filter((n) => !n.read)
  const critical = unread.filter((n) => n.severity === 'critical').length
  const warnings = unread.filter((n) => n.severity === 'warning').length
  items.push({
    key: 'alerts',
    label: 'Unread alerts',
    value: String(unread.length),
    tone: critical > 0 ? 'bad' : warnings > 0 ? 'warn' : 'muted',
    hint: critical + warnings > 0 ? `${critical} critical · ${warnings} warning` : undefined,
  })

  const cpu = telemetryValue(state, 'cpu_percent')
  const ram = telemetryValue(state, 'ram_percent')
  items.push({
    key: 'host',
    label: 'CPU / RAM',
    value: cpu === null && ram === null ? DASH : `${cpu === null ? DASH : `${cpu.toFixed(0)}%`} / ${ram === null ? DASH : `${ram.toFixed(0)}%`}`,
    tone: 'muted',
  })

  const recentEvents = [...state.events]
    .sort((a, b) => (a.timestamp < b.timestamp ? 1 : a.timestamp > b.timestamp ? -1 : 0))
    .slice(0, options.recentEvents)
    .map((e) => ({
      id: e.id,
      time: clockTime(e.timestamp),
      severity: e.severity,
      text: e.message || e.type,
    }))

  return { items, recentEvents, dataAgeSeconds, stale }
}
