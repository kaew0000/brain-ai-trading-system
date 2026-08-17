/**
 * V16 — Train Monitor tab support logic.
 *
 * Kept as a tiny pure module (mirrors src/lib/lifecycleControl.ts's own
 * pattern) so the one piece of actual logic on this page — "how many
 * dataset rows have appeared since the tab was opened" — is unit
 * tested directly, rather than only reachable through a rendered
 * component.
 */

/**
 * Rows added to the training dataset since `firstObserved` (the row
 * count first seen this page session — set once, by the caller, on
 * first successful poll). Returns null until there's something to
 * compare against, rather than 0 — 0 is a real, meaningful answer
 * ("no growth yet") and must stay distinguishable from "no data yet".
 */
export function computeRowsGrowth(
  firstObserved: number | null,
  current: number | null | undefined,
): number | null {
  if (firstObserved == null || typeof current !== 'number') return null
  return current - firstObserved
}
