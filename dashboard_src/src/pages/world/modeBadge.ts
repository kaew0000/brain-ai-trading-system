// V16 §94 — how the World labels the execution mode it is showing, in every mode. Pure so it is unit-testable.
import type { WorldMode } from './types'

export interface ModeBadgeInfo {
  label: string
  detail: string
  className: string
}

const BASE = 'text-xs rounded-full px-2 py-1 border'

/** Badge text + colour for a mode. Unknown or missing context renders a neutral badge instead of hiding. */
export function describeMode(ctx: WorldMode | null | undefined): ModeBadgeInfo {
  if (!ctx) return { label: 'MODE ?', detail: 'Execution mode unavailable', className: `${BASE} border-slate-600 text-slate-400` }
  const lane = ctx.lane ? `${ctx.lane} lane` : 'lane unknown'
  const figures = ctx.laneScoped && ctx.lane ? `figures: ${lane} only` : 'figures: all lanes combined'
  switch (ctx.mode) {
    case 'live':
      return { label: 'LIVE · real money', detail: figures, className: `${BASE} border-rose-500 bg-rose-950 text-rose-300` }
    case 'testnet':
      return { label: 'TESTNET', detail: `${figures} · exchange testnet`, className: `${BASE} border-amber-500 bg-amber-950 text-amber-300` }
    case 'paper':
      return { label: 'PAPER', detail: figures, className: `${BASE} border-sky-600 bg-sky-950 text-sky-300` }
    case 'training':
      return { label: 'TRAINING', detail: figures, className: `${BASE} border-sky-600 bg-sky-950 text-sky-300` }
    default:
      return { label: `MODE ${String(ctx.mode).toUpperCase()}`, detail: figures, className: `${BASE} border-slate-600 text-slate-300` }
  }
}
