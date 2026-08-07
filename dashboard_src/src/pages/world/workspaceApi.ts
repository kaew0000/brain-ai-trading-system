// dashboard_src/src/pages/world/workspaceApi.ts
// Phase W12 — thin fetch layer over /api/workspace/*, mirroring api.ts's
// own get/post helpers.

interface WorkspaceEnvelope<T> {
  ok: boolean
  data: T
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`GET ${path} failed: ${res.status}`)
  const envelope = (await res.json()) as WorkspaceEnvelope<T>
  return envelope.data
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`POST ${path} failed: ${res.status}`)
  const envelope = (await res.json()) as WorkspaceEnvelope<T>
  return envelope.data
}

export interface PanelLayout {
  panelId: string
  x: number
  y: number
  width: number
  height: number
  collapsed: boolean
  docked: boolean
  zOrder: number
}

export interface WorkspaceLayout {
  version: number
  panels: PanelLayout[]
  openPanelIds: string[]
}

export interface AgentPanel {
  panelLabel: string
  agentId: string
  roomId: string
  status: string
  heartbeatAgeSeconds: number | null
  latencyMs: number | null
  lastDecision: string | null
  currentTask: string | null
  lastUpdate: string
}

export interface OperationsSummary {
  mode: string
  engineStatus: string
  accountEquity: number | null
  drawdown: number | null
  activeMissionCount: number
  exchangeConnected: boolean
  heartbeatAgeSeconds: number | null
  cpuPercent: number | null
  ramPercent: number | null
  clock: string
}

export interface WorkspaceNotification {
  id: string
  category: string
  roomId: string
  tickNumber: number
  message: string
  agentId: string
  read: boolean
  pinned: boolean
}

export interface MissionWorkspaceItem {
  missionId: string
  title: string
  district: string
  status: string
  bucket: string
}

export interface WorkspaceSearchResult {
  kind: string
  id: string
  label: string
  detail: string
}

export interface HistoryEntry {
  entryId: number
  kind: string
  payload: Record<string, unknown>
  timestamp: string
}

export interface PerformanceOverlay {
  fpsTarget: number
  worldUpdateSeconds: number
  simulationUpdateSeconds: number
  renderSeconds: number | null
  memoryKb: number
  cpuPercent: number | null
}

export const workspaceApi = {
  getLayout: () => get<WorkspaceLayout>('/api/workspace/layout'),
  resizePanel: (panelId: string, width: number, height: number) =>
    post<WorkspaceLayout>(`/api/workspace/layout/panels/${panelId}/resize?width=${width}&height=${height}`),
  collapsePanel: (panelId: string, collapsed: boolean) =>
    post<WorkspaceLayout>(`/api/workspace/layout/panels/${panelId}/collapse?collapsed=${collapsed}`),
  closePanel: (panelId: string) => post<WorkspaceLayout>(`/api/workspace/layout/panels/${panelId}/close`),
  restorePanel: (panelId: string) => post<WorkspaceLayout>(`/api/workspace/layout/panels/${panelId}/restore`),
  resetLayout: () => post<WorkspaceLayout>('/api/workspace/layout/reset'),

  getAgentPanels: () => get<AgentPanel[]>('/api/workspace/agents'),
  getOperationsSummary: () => get<OperationsSummary>('/api/workspace/operations'),

  getNotifications: (category?: string, unreadOnly?: boolean) => {
    const params = new URLSearchParams()
    if (category) params.set('category', category)
    if (unreadOnly) params.set('unread_only', 'true')
    const qs = params.toString()
    return get<WorkspaceNotification[]>(`/api/workspace/notifications${qs ? `?${qs}` : ''}`)
  },
  pinNotification: (id: string) => post(`/api/workspace/notifications/${id}/pin`),
  unpinNotification: (id: string) => post(`/api/workspace/notifications/${id}/unpin`),
  clearNotification: (id: string) => post(`/api/workspace/notifications/${id}/clear`),
  clearAllNotifications: () => post('/api/workspace/notifications/clear-all'),

  getMissionWorkspace: () => get<Record<string, MissionWorkspaceItem[]>>('/api/workspace/missions'),

  search: (q: string, kinds?: string[]) => {
    const params = new URLSearchParams({ q })
    if (kinds?.length) params.set('kinds', kinds.join(','))
    return get<WorkspaceSearchResult[]>(`/api/workspace/search?${params.toString()}`)
  },
  quickNav: (q: string) => get<WorkspaceSearchResult[]>(`/api/workspace/quick-nav?q=${encodeURIComponent(q)}`),

  recordHistory: (kind: string, payload: Record<string, unknown>) =>
    post<HistoryEntry>(`/api/workspace/history?kind=${encodeURIComponent(kind)}`, payload),
  undoNavigation: () => post<HistoryEntry>('/api/workspace/history/undo'),
  getHistory: () => get<HistoryEntry[]>('/api/workspace/history'),

  getPerformanceOverlay: () => get<PerformanceOverlay>('/api/workspace/performance'),
}
