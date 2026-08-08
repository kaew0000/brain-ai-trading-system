// dashboard_src/src/pages/world/WorldPage.tsx
// Phase W10 — Office World, one module of the unified Brain AI Trading
// Command Center (not a separate dashboard). Consumes only /api/world/*
// and /ws/world (api/world_api.py, api/world_ws.py — Track B, additive)
// via world.runtime/world.simulation/world.interaction/world.frontend.
// renderer's own already-public APIs.
import { useEffect, useMemo, useRef, useState } from 'react'
import { worldApi, wsWorld } from './api'
import type { RenderFrame, RoomActivity, SimulationState } from './types'
import { deriveWsStatus, WS_STATUS_CLASSNAME, WS_STATUS_LABEL } from './wsStatus'
import OfficeScene from './components/OfficeScene'
import RoomList from './components/RoomList'
import Inspector from './components/Inspector'
import TimelinePanel from './components/TimelinePanel'
import NotificationsPanel from './components/NotificationsPanel'
import SettingsPanel from './components/SettingsPanel'
import WorkspacePanel from './components/WorkspacePanel'

type TabId = 'scene' | 'timeline' | 'alerts' | 'settings' | 'workspace'

const TABS: { id: TabId; label: string }[] = [
  { id: 'scene', label: 'Office' },
  { id: 'timeline', label: 'Timeline' },
  { id: 'alerts', label: 'Alerts' },
  { id: 'settings', label: 'Settings' },
  { id: 'workspace', label: 'Workspace' },
]

export default function WorldPage() {
  const [rooms, setRooms] = useState<RoomActivity[]>([])
  const [selectedRoomId, setSelectedRoomId] = useState<string | null>(null)
  const [selectedCharacterId, setSelectedCharacterId] = useState<string | null>(null)
  const [frame, setFrame] = useState<RenderFrame | null>(null)
  const [tab, setTab] = useState<TabId>('scene')
  const [wsStatus, setWsStatus] = useState<'LIVE' | 'RECONNECTING' | 'DISCONNECTED'>('DISCONNECTED')
  const hasEverConnectedRef = useRef(false)

  // Initial hydration via REST — matches the same "REST for initial
  // hydration, WebSocket for realtime" split the rest of this dashboard
  // already uses (src/lib/api.ts's ManagedWS channels).
  useEffect(() => {
    worldApi.listRooms().then((list) => {
      setRooms(list)
      if (list.length > 0) setSelectedRoomId((prev) => prev ?? list[0].roomId)
    })
  }, [])

  // Realtime: /ws/world pushes the current SimulationState whenever its
  // tick changes (api/world_ws.py) — keep the room list's activity/
  // occupancy fresh without re-polling REST every second. ManagedWS.on()
  // takes one handler and returns its own unsubscribe function (see
  // src/lib/api.ts) — no named 'message'/'open'/'close' events.
  useEffect(() => {
    const unsubscribe = wsWorld.on((raw: unknown) => {
      const msg = raw as { type: string; data?: SimulationState }
      if ((msg.type === 'init' || msg.type === 'simulation') && msg.data) {
        setRooms(msg.data.rooms)
      }
    })
    return unsubscribe
  }, [])

  useEffect(() => {
    // Phase W13-3 — tri-state (LIVE/RECONNECTING/DISCONNECTED)
    // presentation only; still just polls the one existing
    // wsWorld.readyState (ManagedWS, src/lib/api.ts) — no second
    // connection, no new polling target, no change to the WS client
    // itself. hasEverConnectedRef distinguishes "still trying the
    // very first connection" from "was live, lost it, backing off" —
    // see wsStatus.ts's own docstring.
    const id = setInterval(() => {
      const readyState = wsWorld.readyState
      if (readyState === 'OPEN') hasEverConnectedRef.current = true
      setWsStatus(deriveWsStatus(readyState, hasEverConnectedRef.current))
    }, 1000)
    return () => clearInterval(id)
  }, [])

  useEffect(() => {
    if (!selectedRoomId) return
    worldApi.getRoomFrame(selectedRoomId).then(setFrame).catch(() => setFrame(null))
  }, [selectedRoomId])

  const characterIdsInFrame = useMemo(
    () =>
      (frame?.commands ?? [])
        .filter((c) => c.layer === 'characters')
        .map((c) => c.entityId),
    [frame],
  )

  const handleSelectRoom = (roomId: string) => {
    setSelectedRoomId(roomId)
    setSelectedCharacterId(null)
    worldApi.select('room', roomId).catch(() => undefined)
  }

  const handleSelectCharacter = (agentId: string) => {
    setSelectedCharacterId(agentId)
    worldApi.select('character', agentId).catch(() => undefined)
  }

  return (
    <div className="p-6 space-y-4" data-testid="world-page">
      <header className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-white">Office World</h1>
        <span
          data-testid="world-ws-status"
          data-ws-state={wsStatus}
          className={`text-xs rounded-full px-2 py-1 ${WS_STATUS_CLASSNAME[wsStatus]}`}
        >
          {WS_STATUS_LABEL[wsStatus]}
        </span>
      </header>

      <nav className="flex gap-2 border-b border-slate-800 pb-2" data-testid="world-tabs">
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            data-testid={`world-tab-${t.id}`}
            onClick={() => setTab(t.id)}
            className={`px-3 py-1.5 rounded-t text-sm ${
              tab === t.id ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            {t.label}
          </button>
        ))}
      </nav>

      {tab === 'scene' && (
        <div className="grid grid-cols-[240px,1fr,280px] gap-4">
          <div>
            <h2 className="text-xs uppercase text-slate-500 mb-2">Rooms</h2>
            <RoomList rooms={rooms} selectedRoomId={selectedRoomId} onSelect={handleSelectRoom} />
          </div>
          <div className="space-y-2">
            <OfficeScene frame={frame} />
            {characterIdsInFrame.length > 0 && (
              <div className="flex flex-wrap gap-2" data-testid="character-chip-list">
                {characterIdsInFrame.map((agentId) => (
                  <button
                    key={agentId}
                    type="button"
                    onClick={() => handleSelectCharacter(agentId)}
                    className={`text-xs rounded-full px-2 py-1 border ${
                      selectedCharacterId === agentId
                        ? 'border-sky-400 text-sky-300'
                        : 'border-slate-700 text-slate-400'
                    }`}
                  >
                    {agentId}
                  </button>
                ))}
              </div>
            )}
          </div>
          <div>
            <h2 className="text-xs uppercase text-slate-500 mb-2">Inspector</h2>
            <Inspector
              kind={selectedCharacterId ? 'character' : 'room'}
              targetId={selectedCharacterId ?? selectedRoomId}
            />
          </div>
        </div>
      )}

      {tab === 'timeline' && <TimelinePanel />}
      {tab === 'alerts' && <NotificationsPanel />}
      {tab === 'settings' && <SettingsPanel rooms={rooms.map((r) => r.roomId)} />}
      {tab === 'workspace' && <WorkspacePanel />}
    </div>
  )
}
