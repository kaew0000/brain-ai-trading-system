// dashboard_src/src/pages/world/components/SystemPulse.tsx
// V16 §82 — compact live strip above the Office scene: the system's real
// numbers (from /api/world/state) and the health of the world clock itself
// (/api/world/ticker), refreshed every WORLD_CONFIG.pulsePollMs. All
// formatting lives in ../pulse.ts; this component only fetches and renders.
import { useEffect, useMemo, useState } from 'react'
import { WORLD_CONFIG } from '../../../game/config/world.config'
import { worldApi } from '../api'
import { buildPulse } from '../pulse'
import type { PulseTone } from '../pulse'
import type { TickerHealth, WorldStateSnapshot } from '../types'

const TONE_CLASS: Record<PulseTone, string> = {
  ok: 'text-emerald-300',
  warn: 'text-amber-300',
  bad: 'text-rose-300',
  muted: 'text-slate-200',
}

const SEVERITY_CLASS: Record<string, string> = {
  critical: 'text-rose-300',
  warning: 'text-amber-300',
  success: 'text-emerald-300',
  info: 'text-slate-400',
}

export default function SystemPulse() {
  const [state, setState] = useState<WorldStateSnapshot | null>(null)
  const [ticker, setTicker] = useState<TickerHealth | null>(null)
  const [failed, setFailed] = useState(false)
  const [nowMs, setNowMs] = useState(() => Date.now())

  useEffect(() => {
    let cancelled = false
    const load = () => {
      Promise.allSettled([worldApi.getWorldState(), worldApi.getTicker()]).then(([s, t]) => {
        if (cancelled) return
        if (s.status === 'fulfilled') setState(s.value)
        if (t.status === 'fulfilled') setTicker(t.value)
        setFailed(s.status === 'rejected')
        setNowMs(Date.now())
      })
    }
    load()
    const id = setInterval(load, WORLD_CONFIG.pulsePollMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  }, [])

  const model = useMemo(
    () =>
      buildPulse(state, ticker, nowMs, {
        staleSeconds: WORLD_CONFIG.pulseStaleSeconds,
        recentEvents: WORLD_CONFIG.pulseRecentEvents,
      }),
    [state, ticker, nowMs],
  )

  return (
    <section
      className="rounded-lg border border-slate-800 bg-slate-900/60 p-3 space-y-2"
      data-testid="system-pulse"
      data-stale={model.stale ? 'true' : 'false'}
    >
      <div className="flex items-center justify-between">
        <h2 className="text-xs uppercase text-slate-500">System Pulse</h2>
        {failed && (
          <span className="text-xs text-amber-300" data-testid="system-pulse-error">
            Could not load system state
          </span>
        )}
      </div>
      <dl className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-6 gap-x-4 gap-y-2">
        {model.items.map((item) => (
          <div key={item.key} data-testid={`pulse-${item.key}`} title={item.hint}>
            <dt className="text-[10px] uppercase tracking-wide text-slate-500">{item.label}</dt>
            <dd className={`text-sm font-medium ${TONE_CLASS[item.tone]}`}>{item.value}</dd>
          </div>
        ))}
      </dl>
      {model.recentEvents.length > 0 && (
        <ul className="border-t border-slate-800 pt-2 space-y-0.5" data-testid="pulse-events">
          {model.recentEvents.map((e) => (
            <li key={e.id} className="text-xs flex gap-2">
              <span className="text-slate-500 tabular-nums">{e.time}</span>
              <span className={SEVERITY_CLASS[e.severity] ?? 'text-slate-400'}>{e.severity}</span>
              <span className="text-slate-300 truncate">{e.text}</span>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
