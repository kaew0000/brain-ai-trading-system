// V16 §83 — meeting setup + live transcript (rule-based NPC turns).
import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CHANNEL_MEETING, MEETING_TURNS, canStartMeeting, chatApi, clampTurns, isMeetingActive, mergeMessages,
  type ChatMessage, type Meeting, type MeetingMode,
} from '../chatApi'
import type { AgentPanel } from '../workspaceApi'

const POLL_MS = 1500

export default function MeetingPanel({ agents }: { agents: AgentPanel[] }) {
  const [meeting, setMeeting] = useState<Meeting | null>(null)
  const [transcript, setTranscript] = useState<ChatMessage[]>([])
  const [selected, setSelected] = useState<string[]>([])
  const [turns, setTurns] = useState<number>(MEETING_TURNS.default)
  const [mode, setMode] = useState<MeetingMode>('auto')
  const [hybrid, setHybrid] = useState(false)
  const [topic, setTopic] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [draft, setDraft] = useState('')
  const lastIdRef = useRef<string | undefined>(undefined)
  const startedRef = useRef<string>('')

  // Default: everyone participates once the roster arrives.
  useEffect(() => {
    setSelected((prev) => (prev.length === 0 ? agents.map((a) => a.agentId) : prev))
  }, [agents])

  const refresh = useCallback(async () => {
    try {
      const m = await chatApi.getMeeting()
      setMeeting(m)
      if (m.meetingId !== startedRef.current) {
        startedRef.current = m.meetingId
        lastIdRef.current = undefined
        setTranscript([])
      }
      const incoming = await chatApi.getMessages(CHANNEL_MEETING, lastIdRef.current)
      if (incoming.length > 0) {
        lastIdRef.current = incoming[incoming.length - 1].id
        setTranscript((prev) => mergeMessages(prev, incoming))
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    void refresh()
    const id = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await fn()
      setError(null)
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const active = isMeetingActive(meeting)

  return (
    <section className="space-y-3" data-testid="meeting-panel">
      {!active && (
        <div className="space-y-3 rounded border border-slate-800 bg-slate-900/60 p-3" data-testid="meeting-setup">
          <div>
            <p className="mb-1 text-xs text-slate-400">Participants</p>
            <div className="flex flex-wrap gap-2">
              {agents.map((a) => (
                <label key={a.agentId} className="flex items-center gap-1 rounded-full border border-slate-700 px-2 py-0.5 text-xs text-slate-200">
                  <input type="checkbox" checked={selected.includes(a.agentId)} onChange={() => toggle(a.agentId)}
                    data-testid={`meeting-participant-${a.agentId}`} />
                  {a.panelLabel}
                </label>
              ))}
            </div>
          </div>
          <label className="block text-xs text-slate-400">
            Max turns: <strong className="text-white" data-testid="meeting-turns-value">{turns}</strong>
            <input type="range" min={MEETING_TURNS.min} max={MEETING_TURNS.max} value={turns}
              onChange={(e) => setTurns(clampTurns(Number(e.target.value)))} className="w-full" data-testid="meeting-turns" />
          </label>
          <div className="flex items-center gap-4 text-xs text-slate-300">
            <label><input type="radio" name="meeting-mode" checked={mode === 'auto'} onChange={() => setMode('auto')} /> Auto</label>
            <label><input type="radio" name="meeting-mode" checked={mode === 'manual'} onChange={() => setMode('manual')} /> Manual</label>
          </div>
          <label className="flex items-center gap-2 text-xs text-slate-300">
            <input type="checkbox" checked={hybrid} disabled={mode !== 'auto'} onChange={(e) => setHybrid(e.target.checked)} />
            Hybrid (your message pauses auto mode)
          </label>
          <textarea value={topic} onChange={(e) => setTopic(e.target.value)} placeholder="Meeting topic, e.g. today's priorities"
            data-testid="meeting-topic" rows={2} maxLength={500}
            className="w-full rounded border border-slate-700 bg-slate-900 p-2 text-sm text-white" />
          <button type="button" disabled={busy || !canStartMeeting(topic, selected)} data-testid="meeting-start"
            onClick={() => void run(() => chatApi.startMeeting({ topic, participants: selected, maxTurns: turns, mode, hybrid }))}
            className="w-full rounded bg-emerald-700 py-2 text-sm font-medium text-white disabled:opacity-40">
            Start meeting
          </button>
        </div>
      )}

      {meeting && meeting.meetingId !== '' && (
        <div className="space-y-2" data-testid="meeting-live">
          <div className="flex items-center justify-between text-xs text-slate-300">
            <span data-testid="meeting-status">{meeting.topic} · {meeting.status} · {meeting.turn}/{meeting.maxTurns}</span>
            {active && (
              <span className="flex gap-1">
                {meeting.mode === 'manual' && meeting.status === 'running' && (
                  <button type="button" disabled={busy} onClick={() => void run(chatApi.next)} data-testid="meeting-next"
                    className="rounded bg-sky-700 px-2 py-1 text-white">Next turn</button>
                )}
                {meeting.status === 'running' && (
                  <button type="button" disabled={busy} onClick={() => void run(chatApi.pause)} className="rounded bg-slate-700 px-2 py-1 text-white">Pause</button>
                )}
                {meeting.status === 'paused' && (
                  <button type="button" disabled={busy} onClick={() => void run(chatApi.resume)} className="rounded bg-slate-700 px-2 py-1 text-white">Resume</button>
                )}
                <button type="button" disabled={busy} onClick={() => void run(chatApi.stop)} data-testid="meeting-stop"
                  className="rounded bg-rose-800 px-2 py-1 text-white">Stop</button>
              </span>
            )}
          </div>
          <div className="max-h-[260px] overflow-y-auto rounded border border-slate-800 bg-slate-900/60 p-2 space-y-1" data-testid="meeting-transcript">
            {transcript.map((m) => (
              <p key={m.id} className={`text-sm ${m.senderKind === 'system' ? 'italic text-slate-500' : 'text-slate-100'}`}>
                {m.senderKind !== 'system' && <strong className="mr-1 text-sky-300">{m.senderName}:</strong>}{m.text}
              </p>
            ))}
          </div>
          {active && (
            <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); const t = draft.trim(); if (t) void run(async () => { await chatApi.postMessage(CHANNEL_MEETING, t); setDraft('') }) }}>
              <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Speak in the meeting…" maxLength={2000}
                className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white" />
              <button type="submit" className="rounded bg-emerald-700 px-3 text-sm text-white">Send</button>
            </form>
          )}
        </div>
      )}
      {error && <p className="text-xs text-rose-400" role="alert" data-testid="meeting-error">{error}</p>}
    </section>
  )
}
