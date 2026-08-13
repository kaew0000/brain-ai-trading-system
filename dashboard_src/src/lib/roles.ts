/**
 * V16 Track W14-1 Item 7 — role ordering, mirrors api/auth.py's
 * `class Role(IntEnum): VIEWER=1; OPERATOR=2; ADMIN=3` exactly (ascending
 * privilege). Kept as a tiny pure module, not duplicated inline in every
 * component that needs a role check, and not re-implemented as a second
 * enum with different values — must stay in lockstep with the backend
 * ordering by construction (see this file's own test in
 * src/lib/tests/roles.test.ts for the explicit lockstep assertion).
 */
export const ROLE_ORDER = ['VIEWER', 'OPERATOR', 'ADMIN'] as const
export type RoleName = typeof ROLE_ORDER[number]

/** True if `role` meets or exceeds `required` (both by name, case-insensitive).
 *  A null/undefined/unrecognized role never satisfies any requirement —
 *  fails closed, same posture as the backend's own auth middleware. */
export function hasRole(role: string | null | undefined, required: RoleName): boolean {
  if (!role) return false
  const have = ROLE_ORDER.indexOf(role.toUpperCase() as RoleName)
  const need = ROLE_ORDER.indexOf(required)
  return have !== -1 && have >= need
}
