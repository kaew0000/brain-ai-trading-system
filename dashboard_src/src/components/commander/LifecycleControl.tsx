/**
 * V16 Track W14-1 Item 6 — START/STOP UI.
 *
 * Uses the existing GET /api/command/state (lifecycle_state) and
 * POST /api/command ("start bot"/"stop bot") — no new backend routes.
 * See src/lib/lifecycleControl.ts for the pure state->button mapping.
 *
 * No optimistic UI: clicking START does not flip the button to RUNNING
 * itself. It disables the button, sends the command, and waits for the
 * NEXT confirmed lifecycle_state (either from the immediate re-fetch
 * below, or the regular 5s useCommanderData() poll — whichever lands
 * first). If the command is rejected (bad auth, illegal transition), the
 * button returns to its previous state and the rejection reason is
 * shown — never silently treated as success.
 *
 * Preserves W14-0 semantics entirely client-side: this component knows
 * nothing about in-flight cycles / next-cycle blocking / pause-resume —
 * that enforcement lives entirely in commander/control_state.py and
 * execution's own lifecycle gate; the button is a thin, honest client
 * of that state machine, not a second implementation of it.
 */
import { useState } from 'react'
import { useCommander, useAuth } from '@/stores'
import { api } from '@/lib/api'
import { lifecycleButtonSpec } from '@/lib/lifecycleControl'
import { hasRole } from '@/lib/roles'
import clsx from 'clsx'

const TONE_CLASS: Record<string, string> = {
  stopped:        'bg-surface-2 border-border text-text-secondary hover:border-accent-green hover:text-accent-green',
  running:        'bg-accent-red/15 border-accent-red/40 text-accent-red hover:bg-accent-red/25',
  transitioning:  'bg-surface-2 border-border text-text-muted cursor-wait',
  failed:         'bg-accent-gold/15 border-accent-gold/40 text-accent-gold hover:bg-accent-gold/25',
}

export default function LifecycleControl({ onRequireLogin }: { onRequireLogin: () => void }) {
  const commanderState = useCommander(s => s.state)
  const setCommanderState = useCommander(s => s.setState)
  const { role } = useAuth()
  const [pending, setPending] = useState(false)
  const [lastError, setLastError] = useState<string | null>(null)

  const lifecycleState = commanderState?.lifecycle_state
  const spec = lifecycleButtonSpec(lifecycleState)
  const authorized = hasRole(role, 'OPERATOR')

  async function handleClick() {
    if (!spec.command) return
    if (!authorized) {
      onRequireLogin()
      return
    }
    setPending(true)
    setLastError(null)
    try {
      const result: any = await api.sendCommand(spec.command)
      if (result?.ok === false) {
        // Auth/role rejection at the middleware layer — surfaced with
        // whatever message the backend gave (e.g. "insufficient role").
        setLastError(result.error || 'Command rejected')
      } else if (result?.data?.success === false) {
        // CommandResult with success=false (e.g. illegal transition
        // raced against another tab) — real failure, shown as such.
        setLastError(result.data.message || 'Command not applied')
      }
      // Re-fetch the real state immediately rather than waiting up to 5s
      // for the next useCommanderData() poll — still not optimistic,
      // this is a confirmed read, not an assumption.
      const fresh = await api.commandState()
      setCommanderState(fresh as any)
    } catch (err) {
      setLastError(err instanceof Error ? err.message : 'Command failed')
    } finally {
      setPending(false)
    }
  }

  return (
    <div className="flex items-center gap-2">
      {lastError && (
        <span className="text-[10px] text-accent-red font-mono max-w-[16rem] truncate" title={lastError}>
          {lastError}
        </span>
      )}
      <button
        type="button"
        onClick={handleClick}
        disabled={spec.disabled || pending}
        title={!authorized ? 'Login as OPERATOR to control the bot' : undefined}
        className={clsx(
          'text-[11px] font-mono font-bold px-2.5 py-1 rounded border transition-colors disabled:opacity-60',
          TONE_CLASS[spec.tone],
        )}
      >
        {pending ? '…' : spec.label}
        {!authorized && !spec.disabled ? ' 🔒' : ''}
      </button>
    </div>
  )
}
