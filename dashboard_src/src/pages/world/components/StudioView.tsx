// V16 §83 — "Studio": the office scene with a roster on the left and a
// chat / meeting / kanban / results panel on the right. Composition only;
// all data comes from existing World endpoints plus /api/world/chat/*.
import { useEffect, useState } from 'react'
import OfficeScene from './OfficeScene'
import ChatPanel from './ChatPanel'
import MeetingPanel from './MeetingPanel'
import { KanbanPanel, ResultsPanel } from './KanbanPanel'
import { CHANNEL_OFFICE, chatApi, dmChannel, type Roster } from '../chatApi'
import type { RenderFrame } from '../types'
import { WS_STATUS_CLASSNAME, WS_STATUS_LABEL } from '../wsStatus'

type SideTab = 'chat' | 'meeting' | 'kanban' | 'results'

const SIDE_TABS: { id: SideTab; label: string }[] = [
  { id: 'chat', label: 'Chat' },
  { id: 'meeting', label: 'Meeting' },
  { id: 'kanban', label: 'Kanban' },
  { id: 'results', label: 'Results' },
]

const ROSTER_POLL_MS = 5000

interface StudioViewProps {
  frame: RenderFrame | null
  wsStatus: 'LIVE' | 'RECONNECTING' | 'DISCONNECTED'
}

export default function StudioView({ frame, wsStatus }: StudioViewProps) {
  const [roster, setRoster] = useState<Roster | null>(null)
  const [rosterError, setRosterError] = useState<string | null>(null)
  const [side, setSide] = useState<SideTab>('chat')
  const [channel, setChannel] = useState<string>(CHANNEL_OFFICE)

  useEffect(() => {
    let alive = true
    const load = () => chatApi.getRoster()
      .then((r) => { if (alive) { setRoster(r); setRosterError(null) } })
      .catch((e: unknown) => { if (alive) setRosterError(e instanceof Error ? e.message : String(e)) })
    void load()
    const id = setInterval(() => void load(), ROSTER_POLL_MS)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const agents = roster?.agents ?? []
  const channelTitle = channel === CHANNEL_OFFICE
    ? 'Office (everyone)'
    : `Direct · ${agents.find((a) => dmChannel(a.agentId) === channel)?.panelLabel ?? channel}`

  return (
    <div className="space-y-3" data-testid="studio-view">
      <div className="flex flex-wrap items-center gap-2 text-xs" data-testid="studio-topbar">
        <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200" data-testid="studio-engine">
          Engine: {roster?.engine ?? '…'}
        </span>
        <span className={`rounded-full px-2 py-1 ${WS_STATUS_CLASSNAME[wsStatus]}`}>{WS_STATUS_LABEL[wsStatus]}</span>
        <span className="rounded-full bg-slate-800 px-2 py-1 text-slate-200" data-testid="studio-npc-count">NPC {agents.length}</span>
        {SIDE_TABS.map((t) => (
          <button key={t.id} type="button" data-testid={`studio-side-${t.id}`} onClick={() => setSide(t.id)}
            className={`rounded-full px-3 py-1 ${side === t.id ? 'bg-emerald-700 text-white' : 'bg-slate-800 text-slate-300 hover:text-white'}`}>
            {t.label}
          </button>
        ))}
      </div>

      {rosterError && <p className="text-xs text-rose-400" role="alert" data-testid="studio-error">{rosterError}</p>}

      <div className="grid grid-cols-[200px,1fr,340px] gap-4">
        <aside className="space-y-2" data-testid="studio-roster">
          <h2 className="text-xs uppercase text-slate-500">Conversations</h2>
          <button type="button" onClick={() => { setChannel(CHANNEL_OFFICE); setSide('chat') }}
            className={`w-full rounded px-3 py-2 text-left text-sm ${channel === CHANNEL_OFFICE ? 'bg-slate-700 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>
            Whole office
          </button>
          <h2 className="pt-2 text-xs uppercase text-slate-500">People</h2>
          <ul className="space-y-1">
            {agents.map((a) => (
              <li key={a.agentId}>
                <button type="button" data-testid={`studio-agent-${a.agentId}`}
                  onClick={() => { setChannel(dmChannel(a.agentId)); setSide('chat') }}
                  className={`w-full rounded px-3 py-2 text-left text-sm ${channel === dmChannel(a.agentId) ? 'bg-slate-700 text-white' : 'text-slate-300 hover:bg-slate-800'}`}>
                  <span className="block">{a.panelLabel}</span>
                  <span className="block text-[11px] text-slate-500">{a.status}</span>
                </button>
              </li>
            ))}
          </ul>
        </aside>

        <div><OfficeScene frame={frame} /></div>

        <aside data-testid="studio-side">
          {side === 'chat' && <ChatPanel key={channel} channel={channel} title={channelTitle} agents={agents} />}
          {side === 'meeting' && <MeetingPanel agents={agents} />}
          {side === 'kanban' && <KanbanPanel />}
          {side === 'results' && <ResultsPanel agents={agents} />}
        </aside>
      </div>
    </div>
  )
}
