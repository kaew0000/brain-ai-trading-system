/**
 * V16 Track W14-1 Item 7 — Operator login.
 *
 * A single API-key field that exchanges for a session Bearer token via
 * the EXISTING POST /api/auth/token (api/app.py) — no new auth system,
 * no hardcoded secret, no key ever baked into the build (it's typed in
 * at runtime by the operator). On failure this shows the backend's own
 * error message; it never pretends success.
 */
import { useState } from 'react'
import { useAuth } from '@/stores'

export default function LoginModal({ onClose }: { onClose: () => void }) {
  const { login, loggingIn, error } = useAuth()
  const [apiKey, setApiKey] = useState('')

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!apiKey.trim()) return
    const ok = await login(apiKey.trim())
    if (ok) onClose()
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onClick={e => e.stopPropagation()}
        onSubmit={submit}
        className="bg-surface-1 border border-border rounded-lg p-5 w-80 space-y-3"
      >
        <div className="text-sm font-mono font-bold text-text-primary">Operator Login</div>
        <p className="text-[11px] text-text-muted">
          Required to START/STOP the bot. Your API key is exchanged for a
          session token — it is never stored on this device.
        </p>
        <input
          autoFocus
          type="password"
          value={apiKey}
          onChange={e => setApiKey(e.target.value)}
          placeholder="API key"
          className="w-full bg-surface-2 border border-border rounded px-2 py-1.5 text-sm font-mono text-text-primary outline-none focus:border-accent-blue"
        />
        {error && <div className="text-xs text-accent-red">{error}</div>}
        <div className="flex items-center gap-2 justify-end pt-1">
          <button
            type="button"
            onClick={onClose}
            className="text-xs px-2.5 py-1 rounded text-text-muted hover:text-text-primary"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={loggingIn || !apiKey.trim()}
            className="text-xs px-3 py-1 rounded bg-accent-blue text-white disabled:opacity-50"
          >
            {loggingIn ? 'Signing in…' : 'Sign in'}
          </button>
        </div>
      </form>
    </div>
  )
}
