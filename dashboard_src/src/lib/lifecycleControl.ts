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

/**
 * V16 fix(lifecycle-control-login-lockout): what the <button disabled>
 * attribute should actually be, as distinct from spec.disabled.
 *
 * Root cause this exists to fix: an unauthenticated viewer has no
 * lifecycle_state at all (GET /api/command/state is 401'd, so
 * useCommander's state stays undefined forever) — lifecycleButtonSpec()
 * correctly reports that as disabled:true ("never guess a transition
 * against an unconfirmed state"), which is the right call for the
 * START/STOP *command* itself. But LifecycleControl.tsx's only path to
 * opening the login modal is a click on this SAME button — so an
 * unauthenticated user landed on a real HTML `disabled` button that can
 * never fire a click event, with no other control anywhere in the UI
 * that opens the login modal. Confirmed via a live session: the button
 * renders (a real element, correctly positioned), but is inert no
 * matter how precisely it's tapped, on any device or zoom level.
 *
 * The fix: while unauthorized, ignore spec.disabled entirely (that
 * reasoning only applies once we're actually allowed to submit a
 * command) — the button must stay clickable so onRequireLogin() can
 * fire. Once authorized, defer to spec.disabled exactly as before;
 * this changes nothing about the "no optimistic UI" / "never guess a
 * transition" guarantees for an authenticated operator.
 */
export function lifecycleButtonInert(
  spec: Pick<LifecycleButtonSpec, 'disabled'>,
  authorized: boolean,
  pending: boolean,
): boolean {
  if (!authorized) return pending
  return spec.disabled || pending
}

export type LifecycleButtonTone = LifecycleButtonSpec['tone'] | 'login'

export interface LifecycleButtonDisplay {
  label: string
  tone: LifecycleButtonTone
}

/**
 * V16 fix(lifecycle-control-unauth-visibility): what the button should
 * actually *look like* to an unauthorized viewer, as distinct from
 * lifecycleButtonSpec() (which still governs real START/STOP semantics
 * once authorized — untouched by this function).
 *
 * Root cause: lifecycleButtonInert() (fix/lifecycle-control-login-lockout)
 * already made the button clickable while unauthorized so it can open the
 * login modal, but LifecycleControl.tsx still sourced the button's visible
 * label/tone from spec regardless of auth. The most common unauthorized
 * case — a viewer who has never logged in — has lifecycle_state
 * permanently undefined, since GET /api/command/state 401s. That's
 * lifecycleButtonSpec()'s default branch: label '…', tone 'transitioning'
 * (muted colors + cursor-wait), disabled:true. Muted/'…'/cursor-wait reads
 * as "loading, nothing to do here" rather than "click to log in", and
 * disabled:true also suppressed the caller's old "🔒 suffix" (only shown
 * when `!spec.disabled`) in exactly this case — net effect, a real,
 * clickable element with no visible affordance that it does anything.
 * Confirmed against a live unauthenticated session: the click handler
 * fires correctly, but there is nothing on screen inviting the click.
 *
 * Fix: while unauthorized, label/tone are fully decoupled from spec —
 * the same posture handleClick() already takes (spec.command is never
 * read until after the authorized check). Once authorized, this returns
 * spec's own label/tone unchanged, so the authorized flow (including the
 * in-flight "pending" state) is byte-for-byte identical to before.
 */
export function lifecycleButtonDisplay(
  spec: Pick<LifecycleButtonSpec, 'label' | 'tone'>,
  authorized: boolean,
  pending: boolean,
): LifecycleButtonDisplay {
  if (!authorized) return { label: 'LOGIN', tone: 'login' }
  return { label: pending ? '…' : spec.label, tone: spec.tone }
}
