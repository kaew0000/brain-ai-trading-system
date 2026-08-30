/**
 * V16 — Train Monitor cycle ring support logic.
 *
 * Kept as a tiny pure module (same pattern as lib/trainMonitor.ts's
 * computeRowsGrowth) so the actual math behind the real-time circular
 * progress indicator — "how far through the current background
 * training-lane cycle are we, right now" — is unit tested directly,
 * rather than only reachable through a rendered SVG component.
 *
 * The ring is driven entirely by backend-reported facts
 * (TrainingLaneStatus.last_cycle_at / poll_interval_seconds — see
 * training_lane_runner.py::_cycle()'s heartbeat bookkeeping), not by
 * the page's own 20s poll cadence, so it keeps animating smoothly
 * between polls instead of jumping once every poll.
 */

export interface CycleProgress {
  /** 0 (cycle just started) → 1 (a new cycle is due). Clamped. */
  fraction: number
  /** Whole seconds until the next expected cycle. Never negative — a
   * cycle running long still reads as "0s", not a negative countdown. */
  remainingSeconds: number
}

/**
 * Returns null when there isn't yet a real cycle to measure against
 * (lane disabled/stopped, or no cycle observed yet) — same "honest
 * empty state, not a fabricated 0%" posture as computeRowsGrowth
 * returning null rather than guessing.
 */
export function computeCycleProgress(
  nowMs: number,
  lastCycleAtIso: string | null | undefined,
  pollIntervalSeconds: number | null | undefined,
  isRunning: boolean | undefined,
): CycleProgress | null {
  if (!isRunning || !lastCycleAtIso || !pollIntervalSeconds || pollIntervalSeconds <= 0) return null

  const lastCycleMs = new Date(lastCycleAtIso).getTime()
  if (Number.isNaN(lastCycleMs)) return null

  const elapsedSeconds = Math.max(0, (nowMs - lastCycleMs) / 1000)
  const fraction = Math.min(1, elapsedSeconds / pollIntervalSeconds)
  const remainingSeconds = Math.max(0, Math.ceil(pollIntervalSeconds - elapsedSeconds))

  return { fraction, remainingSeconds }
}
