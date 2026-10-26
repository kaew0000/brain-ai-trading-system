// V16 §83 — Kanban (missions by bucket) and Results (latest agent
// decisions). Read-only views over the existing /api/workspace/* data.
import { useEffect, useState } from 'react'
import { workspaceApi, type AgentPanel, type MissionWorkspaceItem } from '../workspaceApi'

const BUCKETS = ['waiting', 'active', 'completed', 'blocked'] as const
const POLL_MS = 5000

export function KanbanPanel() {
  const [data, setData] = useState<Record<string, MissionWorkspaceItem[]>>({})
  const [error, setError] = useState<string | null>(null)
  useEffect(() => {
    let alive = true
    const load = () => workspaceApi.getMissionWorkspace()
      .then((d) => { if (alive) { setData(d); setError(null) } })
      .catch((e: unknown) => { if (alive) setError(e instanceof Error ? e.message : String(e)) })
    void load()
    const id = setInterval(() => void load(), POLL_MS)
    return () => { alive = false; clearInterval(id) }
  }, [])
  return (
    <section className="grid grid-cols-2 gap-2" data-testid="kanban-panel">
      {BUCKETS.map((b) => (
        <div key={b} className="rounded border border-slate-800 bg-slate-900/60 p-2">
          <h4 className="mb-1 text-[11px] uppercase text-slate-500">{b} ({(data[b] ?? []).length})</h4>
          <ul className="space-y-1">
            {(data[b] ?? []).map((m) => <li key={m.missionId} className="rounded bg-slate-800 px-2 py-1 text-xs text-slate-100">{m.title}</li>)}
          </ul>
        </div>
      ))}
      {error && <p className="col-span-2 text-xs text-rose-400" role="alert">{error}</p>}
    </section>
  )
}

export function ResultsPanel({ agents }: { agents: AgentPanel[] }) {
  return (
    <ul className="space-y-1" data-testid="results-panel">
      {agents.map((a) => (
        <li key={a.agentId} className="rounded border border-slate-800 bg-slate-900/60 px-2 py-1.5 text-xs">
          <strong className="text-sky-300">{a.panelLabel}</strong>
          <span className="text-slate-400"> · {a.status}</span>
          <p className="text-slate-200">{a.lastDecision ?? 'No decision reported yet'}</p>
        </li>
      ))}
    </ul>
  )
}
