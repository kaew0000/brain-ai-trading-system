// dashboard_src/src/lib/bootToken.ts
//
// V16 — console/log-based dashboard auto-login. Companion to
// main.py::_boot_login_url(), which auto-opens the browser at
// "http://localhost:<port>/?token=<api_key>" printed to its own
// startup console log, instead of requiring the operator to type an
// API key into the dashboard's LoginModal.
//
// Pulled out of components/layout/Layout.tsx as a pure function so the
// URL-parsing/stripping logic is unit-testable without a React render
// harness (this repo's frontend tests only exercise lib/ logic
// modules — see lifecycleControl.ts, roles.ts — not component
// rendering, so this follows the same pattern rather than introducing
// a new testing-library dependency for one small piece of logic).

export interface ParsedBootToken {
  /** The token value, or null if none was present in `search`. */
  token: string | null
  /** `search` with the `token` param removed, otherwise unchanged
   *  (other query params and the leading '?' are preserved as-is). */
  strippedSearch: string
}

/** Extracts a `token` query param from a location.search string (e.g.
 *  "?token=abc123&x=1") and returns what the URL bar should show after
 *  consuming it (e.g. "?x=1", or "" if nothing else was there). Pure —
 *  does not touch window/history itself, so callers control exactly
 *  when/whether the URL is actually rewritten. */
export function parseBootToken(search: string): ParsedBootToken {
  const params = new URLSearchParams(search)
  const token = params.get('token')
  if (token === null) {
    return { token: null, strippedSearch: search }
  }
  params.delete('token')
  const rest = params.toString()
  return { token, strippedSearch: rest ? `?${rest}` : '' }
}
