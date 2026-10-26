// V16 §83 — room / direct chat. Polls /api/world/chat/messages; replies
// are rule-based (built from real agent state on the backend).
import { useCallback, useEffect, useRef, useState } from 'react'
import { chatApi, insertMention, mergeMessages, type ChatMessage } from '../chatApi'
import type { AgentPanel } from '../workspaceApi'

const POLL_MS = 2000

interface ChatPanelProps {
  channel: string
  title: string
  agents: AgentPanel[]
}

export default function ChatPanel({ channel, title, agents }: ChatPanelProps) {
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [sending, setSending] = useState(false)
  const lastIdRef = useRef<string | undefined>(undefined)
  const endRef = useRef<HTMLDivElement | null>(null)

  const refresh = useCallback(async () => {
    try {
      const incoming = await chatApi.getMessages(channel, lastIdRef.current)
      if (incoming.length > 0) {
        lastIdRef.current = incoming[incoming.length - 1].id
        setMessages((prev) => mergeMessages(prev, incoming))
      }
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [channel])

  useEffect(() => {
    setMessages([])
    lastIdRef.current = undefined
    void refresh()
    const id = setInterval(() => void refresh(), POLL_MS)
    return () => clearInterval(id)
  }, [refresh])

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: 'end' })
  }, [messages.length])

  const send = async () => {
    const text = draft.trim()
    if (!text || sending) return
    setSending(true)
    try {
      await chatApi.postMessage(channel, text)
      setDraft('')
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSending(false)
    }
  }

  return (
    <section className="flex h-full flex-col gap-2" data-testid="chat-panel">
      <h3 className="text-sm font-semibold text-white">{title}</h3>
      <div className="flex-1 min-h-[160px] max-h-[360px] overflow-y-auto rounded border border-slate-800 bg-slate-900/60 p-2 space-y-1.5" data-testid="chat-messages">
        {messages.length === 0 && <p className="text-xs italic text-slate-500">No messages yet. Mention an agent with @.</p>}
        {messages.map((m) => (
          <div key={m.id} data-testid={`chat-msg-${m.senderKind}`} className={m.senderKind === 'user' ? 'text-right' : ''}>
            <span className="text-[10px] uppercase text-slate-500">{m.senderName}</span>
            <p className={`inline-block max-w-full rounded px-2 py-1 text-sm ${m.senderKind === 'user' ? 'bg-emerald-800 text-white' : m.senderKind === 'system' ? 'text-slate-400 italic' : 'bg-slate-800 text-slate-100'}`}>
              {m.text}
            </p>
          </div>
        ))}
        <div ref={endRef} />
      </div>
      {error && <p className="text-xs text-rose-400" role="alert" data-testid="chat-error">{error}</p>}
      <div className="flex flex-wrap gap-1" data-testid="chat-mention-chips">
        {agents.map((a) => (
          <button key={a.agentId} type="button" onClick={() => setDraft((d) => insertMention(d, a))}
            className="rounded-full border border-slate-700 px-2 py-0.5 text-[11px] text-slate-300 hover:border-sky-400">
            @{a.panelLabel}
          </button>
        ))}
      </div>
      <form className="flex gap-2" onSubmit={(e) => { e.preventDefault(); void send() }}>
        <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Message… (@[CEO] status?)"
          maxLength={2000} data-testid="chat-input"
          className="flex-1 rounded border border-slate-700 bg-slate-900 px-2 py-1.5 text-sm text-white" />
        <button type="submit" disabled={sending || draft.trim().length === 0} data-testid="chat-send"
          className="rounded bg-emerald-700 px-3 py-1.5 text-sm text-white disabled:opacity-40">Send</button>
      </form>
    </section>
  )
}
