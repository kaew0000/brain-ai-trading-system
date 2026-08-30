/**
 * CycleRing — real-time circular progress ring for the Background
 * Training Lane's cycle (Train Monitor tab, requested directly: "show
 * this tab's training process live, as a graphical cycle circle, with
 * easy-to-understand detail").
 *
 * No charting library exists in this project (see MiniChart.tsx's own
 * doc comment), so this follows the same convention: a small
 * hand-rolled SVG, colors passed as hex (Tailwind classes aren't
 * usable inline on SVG stroke/fill), animated with framer-motion
 * (already a dependency — ConfBar in components/common/index.tsx uses
 * the identical motion.div width-tween pattern this mirrors for
 * strokeDashoffset).
 *
 * Ticks its own 1s-local clock independently of the page's 20s poll
 * (see TrainMonitor.tsx) so the ring animates smoothly between polls
 * instead of jumping once every poll — the *fraction* is always
 * recomputed from the real, backend-reported last_cycle_at, never
 * fabricated locally (see lib/cycleRing.ts::computeCycleProgress).
 */
import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import clsx from 'clsx'
import { computeCycleProgress } from '@/lib/cycleRing'

const SIZE = 88
const STROKE = 7
const RADIUS = (SIZE - STROKE) / 2
const CIRCUMFERENCE = 2 * Math.PI * RADIUS

// Tailwind config's accent.green / accent.gold / text.muted / surface.3 —
// see dashboard_src/tailwind.config.js. Kept in sync manually since SVG
// can't consume Tailwind classes directly (same constraint MiniChart.tsx
// documents for its own stroke colors).
const TRACK_COLOR = '#1e1e38'
const RUNNING_COLOR = '#10b981'
const DUE_SOON_COLOR = '#fbbf24'
const IDLE_COLOR = '#475569'

export function CycleRing({
  isRunning,
  pollIntervalSeconds,
  lastCycleAt,
  cycleCount,
  summary,
}: {
  isRunning?: boolean
  pollIntervalSeconds?: number | null
  lastCycleAt?: string | null
  cycleCount?: number | null
  summary?: string
}) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])

  const progress = computeCycleProgress(now, lastCycleAt, pollIntervalSeconds, isRunning)
  const fraction = progress?.fraction ?? 0
  const ringColor = !progress ? IDLE_COLOR : fraction > 0.85 ? DUE_SOON_COLOR : RUNNING_COLOR

  return (
    <div className="flex items-center gap-3">
      <div className="relative shrink-0" style={{ width: SIZE, height: SIZE }}>
        <svg width={SIZE} height={SIZE} viewBox={`0 0 ${SIZE} ${SIZE}`} className="-rotate-90">
          <circle cx={SIZE / 2} cy={SIZE / 2} r={RADIUS} fill="none" stroke={TRACK_COLOR} strokeWidth={STROKE} />
          <motion.circle
            cx={SIZE / 2}
            cy={SIZE / 2}
            r={RADIUS}
            fill="none"
            stroke={ringColor}
            strokeWidth={STROKE}
            strokeLinecap="round"
            strokeDasharray={CIRCUMFERENCE}
            animate={{ strokeDashoffset: CIRCUMFERENCE * (1 - fraction) }}
            transition={{ duration: 0.9, ease: 'linear' }}
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className={clsx('font-mono text-sm', progress ? 'text-text-primary' : 'text-text-muted')}>
            {progress ? `${progress.remainingSeconds}s` : '—'}
          </span>
          <span className="text-[9px] text-text-muted tracking-wide">{progress ? 'NEXT' : 'IDLE'}</span>
        </div>
      </div>
      <div className="flex flex-col gap-1 min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-[10px] text-text-muted">Cycle</span>
          <span className="font-mono text-xs text-text-primary">{cycleCount ?? '—'}</span>
        </div>
        <div className="text-xs text-text-secondary truncate max-w-[220px]" title={summary}>
          {summary || 'Waiting for first cycle…'}
        </div>
      </div>
    </div>
  )
}
