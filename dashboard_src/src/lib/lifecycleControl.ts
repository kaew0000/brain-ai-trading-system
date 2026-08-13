/**
 * V16 Track W14-1 Item 6 — START/STOP button state, derived purely from
 * the real lifecycle_state (commander/control_state.py: STOPPED ->
 * STARTING -> RUNNING -> STOPPING -> STOPPED, or -> FAILED). No
 * optimistic "assume it worked" state exists here — the button always
 * reflects the last lifecycle_state actually confirmed by the backend
 * (see components/commander/LifecycleControl.tsx for how in-flight
 * commands are shown separately from this).
 */
import type { CommandState } from '@/types/api'

export type LifecycleState = NonNullable<CommandState['lifecycle_state']>

export interface LifecycleButtonSpec {
  label: string
  command: 'start bot' | 'stop bot' | null
  disabled: boolean
  tone: 'stopped' | 'running' | 'transitioning' | 'failed'
}

/** Mirrors _LEGAL_LIFECYCLE_TRANSITIONS in commander/control_state.py —
 *  used only to decide whether to offer a button, never to bypass the
 *  backend's own check (that check is the actual source of truth; a
 *  race where this is stale just makes POST /api/command return
 *  matched=false, handled by the caller, not a safety issue). */
export function lifecycleButtonSpec(state: LifecycleState | undefined): LifecycleButtonSpec {
  switch (state) {
    case 'STOPPED':
      return { label: 'START', command: 'start bot', disabled: false, tone: 'stopped' }
    case 'FAILED':
      return { label: 'RESTART', command: 'start bot', disabled: false, tone: 'failed' }
    case 'RUNNING':
      return { label: 'STOP', command: 'stop bot', disabled: false, tone: 'running' }
    case 'STARTING':
      return { label: 'STARTING…', command: null, disabled: true, tone: 'transitioning' }
    case 'STOPPING':
      return { label: 'STOPPING…', command: null, disabled: true, tone: 'transitioning' }
    default:
      // Unknown/not-yet-polled — never guess; disable rather than offer
      // a transition against a state we haven't actually confirmed.
      return { label: '…', command: null, disabled: true, tone: 'transitioning' }
  }
}
