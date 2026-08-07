// dashboard_src/src/pages/world/components/WorkspacePanel.tsx
// Phase W12 — Live Operations Workspace & Command Console. Consumes only
// /api/workspace/* (api/workspace_api.py -> world.workspace.api), which
// itself only reads world.runtime/world.simulation/world.interaction —
// no duplicated business logic, no new polling loop (this component
// polls the same way every other panel in this dashboard already does).
//
// Scoping note (documented, not silently narrowed): "resizable/dockable
// panels" here means each panel has a persisted width/height/collapsed
// state adjustable via visible controls (+/- buttons, a collapse
// toggle) rather than free-form mouse drag-resize — consistent with
// how Phase W10 scoped "Window Manager" down to this dashboard's own
// established pattern (no drag-and-drop framework exists anywhere else
// in this codebase either).
import { useEffect, useMemo, useState } from 'react'
import { workspaceApi } from '../workspaceApi'
import type {
  AgentPanel,
  HistoryEntry,
  MissionWorkspaceItem,
  OperationsSummary,
  PanelLayout,
  PerformanceOverlay,
  WorkspaceNotification,
  WorkspaceSearchResult,
} from '../workspaceApi'

const STATUS_COLOR: Record<string, string> = {
  idle: 'text-slate-400', walking: 'text-sky-400', working: 'text-green-400',
  meeting: 'text-purple-400', emergency: 'text-red-400', celebration: 'text-amber-400',
  resting: 'text-slate-500',
}

function usePolled<T>(fetcher: () => Promise<T>, intervalMs: number, deps: unknown[] = []): T | null {
  const [value, setValue] = useState<T | null>(null)
  useEffect(() => {
    let cancelled = false
    const run = () => fetcher().then((v) => !cancelled && setValue(v)).catch(() => undefined)
    run()
    const id = setInterval(run, intervalMs)
    return () => {
      cancelled = true
      clearInterval(id)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)
  return value
}

function PanelChrome({
  panel, title, onCollapse, onResize, children,
}: {
  panel: PanelLayout | undefined
  title: string
  onCollapse: (collapsed: boolean) => void
  onResize: (delta: number) => void
  children: React.ReactNode
}) {
  const collapsed = panel?.collapsed ?? false
  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/60" data-testid={`panel-${panel?.panelId ?? title}`}>
      <div className="flex items-center justify-between px-3 py-1.5 border-b border-slate-800">
        <span className="text-xs font-semibold text-slate-300">{title}</span>
        <div className="flex items-center gap-1">
          <button type="button" onClick={() => onResize(-20)} className="text-slate-500 hover:text-slate-300 text-xs px-1">
            −
          </button>
          <button type="button" onClick={() => onResize(20)} className="text-slate-500 hover:text-slate-300 text-xs px-1">
            +
          </button>
          <button
            type="button"
            data-testid={`collapse-${panel?.panelId ?? title}`}
            onClick={() => onCollapse(!collapsed)}
            className="text-slate-500 hover:text-slate-300 text-xs px-1"
          >
            {collapsed ? '▸' : '▾'}
          </button>
        </div>
      </div>
      {!collapsed && <div className="p-3">{children}</div>}
    </div>
  )
}

export default function WorkspacePanel() {
  const [layout, setLayout] = useState<PanelLayout[]>([])
  const [query, setQuery] = useState('')
  const [searchResults, setSearchResults] = useState<WorkspaceSearchResult[]>([])
  const [paletteOpen, setPaletteOpen] = useState(false)

  const ops = usePolled<OperationsSummary>(workspaceApi.getOperationsSummary, 3000)
  const agents = usePolled<AgentPanel[]>(workspaceApi.getAgentPanels, 3000)
  const notifications = usePolled<WorkspaceNotification[]>(() => workspaceApi.getNotifications(), 4000)
  const missions = usePolled<Record<string, MissionWorkspaceItem[]>>(workspaceApi.getMissionWorkspace, 5000)
  const performance = usePolled<PerformanceOverlay>(workspaceApi.getPerformanceOverlay, 4000)
  const history = usePolled<HistoryEntry[]>(workspaceApi.getHistory, 5000)

  useEffect(() => {
    workspaceApi.getLayout().then((l) => setLayout(l.panels))
  }, [])

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'p') {
        e.preventDefault()
        setPaletteOpen((open) => !open)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [])

  useEffect(() => {
    if (!query.trim()) {
      setSearchResults([])
      return
    }
    const id = setTimeout(() => {
      workspaceApi.search(query).then(setSearchResults).catch(() => setSearchResults([]))
    }, 200)
    return () => clearTimeout(id)
  }, [query])

  const panelById = useMemo(() => Object.fromEntries(layout.map((p) => [p.panelId, p])), [layout])

  const collapse = (panelId: string, collapsed: boolean) => {
    workspaceApi.collapsePanel(panelId, collapsed).then((l) => setLayout(l.panels))
  }
  const resize = (panelId: string, delta: number) => {
    const panel = panelById[panelId]
    if (!panel) return
    workspaceApi
      .resizePanel(panelId, Math.max(200, panel.width + delta), Math.max(120, panel.height + delta * 0.7))
      .then((l) => setLayout(l.panels))
  }

  const agentPanelId = (label: string) => `agent-${label.toLowerCase()}`

  return (
    <div className="space-y-4" data-testid="workspace-panel">
      {/* Feature 3: Operations Dashboard top strip */}
      <div className="flex flex-wrap items-center gap-4 rounded-lg border border-slate-700 bg-slate-900/60 px-4 py-2 text-xs text-slate-300">
        <span>
          Mode: <strong className="text-white uppercase">{ops?.mode ?? '…'}</strong>
        </span>
        <span>Engine: {ops?.engineStatus ?? '…'}</span>
        <span>Drawdown: {ops?.drawdown ?? '—'}</span>
        <span>Missions: {ops?.activeMissionCount ?? 0}</span>
        <span>Exchange: {ops?.exchangeConnected ? 'Connected' : 'Not connected'}</span>
        <span>CPU: {ops?.cpuPercent ?? '—'}</span>
        <span>RAM: {ops?.ramPercent ?? '—'}</span>
        <span className="ml-auto font-mono">{ops?.clock?.slice(11, 19) ?? '--:--:--'}</span>
      </div>

      {/* Feature 6/7: Search + Quick Nav (Ctrl+P) */}
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search rooms, agents, missions, events… (Ctrl+P for quick nav)"
          data-testid="workspace-search-input"
          className="w-full rounded-md border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200"
        />
        {searchResults.length > 0 && (
          <ul data-testid="workspace-search-results" className="absolute z-10 mt-1 w-full rounded-md border border-slate-700 bg-slate-900 max-h-64 overflow-auto">
            {searchResults.slice(0, 20).map((r) => (
              <li key={`${r.kind}-${r.id}`} className="px-3 py-1.5 text-xs text-slate-300 hover:bg-slate-800">
                <span className="text-slate-500 uppercase mr-2">{r.kind}</span>
                {r.label}
              </li>
            ))}
          </ul>
        )}
      </div>

      {paletteOpen && (
        <div data-testid="quick-nav-palette" className="fixed inset-0 z-20 flex items-start justify-center bg-black/50 pt-24" onClick={() => setPaletteOpen(false)}>
          <div className="w-96 rounded-lg border border-slate-700 bg-slate-900 p-3" onClick={(e) => e.stopPropagation()}>
            <input
              autoFocus
              type="text"
              placeholder="Jump to room, agent, mission, notification…"
              className="w-full rounded bg-slate-800 px-2 py-1.5 text-sm text-slate-200"
              onChange={(e) => {
                workspaceApi.quickNav(e.target.value).then(setSearchResults).catch(() => undefined)
              }}
            />
            <ul className="mt-2 max-h-64 overflow-auto">
              {searchResults.slice(0, 10).map((r) => (
                <li key={`${r.kind}-${r.id}`} className="px-2 py-1 text-xs text-slate-300 hover:bg-slate-800 rounded">
                  {r.kind}: {r.label}
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* Feature 2: Live Agent Workspace */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3" data-testid="agent-panel-grid">
        {(agents ?? []).map((a) => (
          <PanelChrome
            key={a.panelLabel}
            panel={panelById[agentPanelId(a.panelLabel)]}
            title={a.panelLabel}
            onCollapse={(c) => collapse(agentPanelId(a.panelLabel), c)}
            onResize={(d) => resize(agentPanelId(a.panelLabel), d)}
          >
            <div className={`text-sm font-semibold ${STATUS_COLOR[a.status] ?? 'text-slate-300'}`}>{a.status}</div>
            <div className="text-xs text-slate-500 mt-1">Heartbeat: {a.heartbeatAgeSeconds ?? '—'}</div>
            <div className="text-xs text-slate-500">Latency: {a.latencyMs ?? '—'}</div>
            <div className="text-xs text-slate-400 mt-1 truncate">Task: {a.currentTask ?? 'none'}</div>
            <div className="text-xs text-slate-400 truncate">Last: {a.lastDecision ?? 'none'}</div>
          </PanelChrome>
        ))}
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        {/* Feature 4: Notification Dock */}
        <PanelChrome
          panel={panelById.notifications}
          title="Notifications"
          onCollapse={(c) => collapse('notifications', c)}
          onResize={(d) => resize('notifications', d)}
        >
          <div className="flex justify-end mb-2">
            <button type="button" onClick={() => workspaceApi.clearAllNotifications()} className="text-xs text-slate-500 hover:text-slate-300">
              Clear all
            </button>
          </div>
          <ul className="space-y-1 max-h-48 overflow-auto" data-testid="workspace-notifications">
            {(notifications ?? []).map((n) => (
              <li key={n.id} className="text-xs flex items-center justify-between gap-2 border-b border-slate-800 pb-1">
                <span className="truncate">{n.message || n.category}</span>
                <span className="flex gap-1 shrink-0">
                  <button type="button" onClick={() => workspaceApi.pinNotification(n.id)} className="text-slate-500 hover:text-amber-400">
                    {n.pinned ? '★' : '☆'}
                  </button>
                  <button type="button" onClick={() => workspaceApi.clearNotification(n.id)} className="text-slate-500 hover:text-red-400">
                    ×
                  </button>
                </span>
              </li>
            ))}
            {(notifications ?? []).length === 0 && <li className="text-slate-500">No alerts.</li>}
          </ul>
        </PanelChrome>

        {/* Feature 5: Mission Workspace */}
        <PanelChrome
          panel={panelById.missions}
          title="Missions"
          onCollapse={(c) => collapse('missions', c)}
          onResize={(d) => resize('missions', d)}
        >
          {Object.entries(missions ?? {}).map(([bucket, items]) => (
            <div key={bucket} className="mb-2">
              <div className="text-xs uppercase text-slate-500">{bucket} ({items.length})</div>
              {items.map((m) => (
                <div key={m.missionId} className="text-xs text-slate-300 truncate">{m.title}</div>
              ))}
            </div>
          ))}
        </PanelChrome>

        {/* Feature 9: Performance Overlay */}
        <PanelChrome
          panel={panelById.performance}
          title="Performance"
          onCollapse={(c) => collapse('performance', c)}
          onResize={(d) => resize('performance', d)}
        >
          <div className="text-xs text-slate-300 space-y-1" data-testid="performance-overlay">
            <div>FPS target: {performance?.fpsTarget ?? '—'}</div>
            <div>World update: {performance ? `${(performance.worldUpdateSeconds * 1000).toFixed(2)}ms` : '—'}</div>
            <div>Simulation update: {performance ? `${(performance.simulationUpdateSeconds * 1000).toFixed(2)}ms` : '—'}</div>
            <div>Memory: {performance ? `${performance.memoryKb.toFixed(0)} KB` : '—'}</div>
          </div>
        </PanelChrome>
      </div>

      {/* Feature 8: Workspace History */}
      <PanelChrome
        panel={panelById.history}
        title="History"
        onCollapse={(c) => collapse('history', c)}
        onResize={(d) => resize('history', d)}
      >
        <div className="flex items-center justify-between mb-2">
          <span className="text-xs text-slate-500">{(history ?? []).length} entries</span>
          <button
            type="button"
            data-testid="workspace-undo"
            onClick={() => workspaceApi.undoNavigation().catch(() => undefined)}
            className="text-xs text-slate-500 hover:text-slate-300"
          >
            Undo
          </button>
        </div>
        <ul className="text-xs text-slate-400 space-y-1 max-h-32 overflow-auto">
          {(history ?? []).slice(-10).reverse().map((h) => (
            <li key={h.entryId}>{h.kind} — {h.timestamp}</li>
          ))}
        </ul>
      </PanelChrome>
    </div>
  )
}
