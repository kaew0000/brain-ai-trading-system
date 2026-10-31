// V16 §94 — shows the execution mode (paper / testnet / live / training) the World is running under.
import { useEffect, useState } from 'react'
import { worldApi } from '../api'
import { describeMode } from '../modeBadge'
import type { WorldMode } from '../types'

const RETRY_MS = 10000

export default function ModeBadge() {
  const [ctx, setCtx] = useState<WorldMode | null>(null)

  useEffect(() => {
    let alive = true
    let timer: ReturnType<typeof setTimeout> | undefined
    const load = () =>
      worldApi
        .getMode()
        .then((m) => { if (alive) setCtx(m) })
        // The mode is fixed for the life of the process; only a failed fetch is retried.
        .catch(() => { if (alive) timer = setTimeout(load, RETRY_MS) })
    void load()
    return () => { alive = false; if (timer) clearTimeout(timer) }
  }, [])

  const info = describeMode(ctx)
  return (
    <span data-testid="world-mode-badge" data-mode={ctx?.mode ?? 'unknown'} title={info.detail} className={info.className}>
      {info.label}
    </span>
  )
}
