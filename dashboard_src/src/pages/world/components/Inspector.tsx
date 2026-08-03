// dashboard_src/src/pages/world/components/Inspector.tsx
import { useEffect, useState } from 'react'
import { worldApi } from '../api'
import type { InspectorReport } from '../types'

interface InspectorProps {
  kind: string
  targetId: string | null
}

export default function Inspector({ kind, targetId }: InspectorProps) {
  const [report, setReport] = useState<InspectorReport | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!targetId) {
      setReport(null)
      return
    }
    let cancelled = false
    worldApi
      .inspect(kind, targetId)
      .then((r) => {
        if (!cancelled) {
          setReport(r)
          setError(null)
        }
      })
      .catch((err) => {
        if (!cancelled) setError(String(err))
      })
    return () => {
      cancelled = true
    }
  }, [kind, targetId])

  if (!targetId) {
    return <p className="text-sm text-slate-500">Select a room or character to inspect it.</p>
  }
  if (error) {
    return <p className="text-sm text-red-400">{error}</p>
  }
  if (!report) {
    return <p className="text-sm text-slate-500">Loading…</p>
  }

  return (
    <div data-testid="inspector-report" className="space-y-2 text-sm">
      <h3 className="font-semibold text-white">{report.targetId as string}</h3>
      <dl className="grid grid-cols-[auto,1fr] gap-x-3 gap-y-1 text-slate-300">
        {Object.entries(report)
          .filter(([key]) => key !== 'kind' && key !== 'targetId')
          .map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-slate-500">{key}</dt>
              <dd className="truncate">{typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd>
            </div>
          ))}
      </dl>
    </div>
  )
}
