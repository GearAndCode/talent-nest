// Shared helper for validating "return to this page after login" targets
// (Careers -> Apply -> Login -> back to the exact job, and any other flow
// that needs to preserve an intended destination through authentication).
//
// Used by both the careers page and the candidate login page so there is
// exactly one definition of what counts as a "safe" internal redirect -
// never duplicate this check inline.
 
/**
 * Returns true only if `path` is a same-origin, in-app route path such as
 * "/candidate/apply/42". Rejects anything that could send the browser
 * off-site or execute script:
 *   - absolute URLs ("https://evil-site.com")
 *   - protocol-relative URLs ("//evil-site.com")
 *   - "javascript:" / "data:" / other non-path schemes
 *   - anything not starting with a single leading "/"
 */
export function isSafeInternalRedirect(path) {
  if (typeof path !== "string" || path.length === 0) return false;
 
  // Must be a root-relative path ("/..."), not "//..." (protocol-relative,
  // which browsers treat as an absolute URL to another host) and not a
  // scheme like "javascript:" or "https:".
  if (!path.startsWith("/") || path.startsWith("//")) return false;
 
  // Belt-and-braces: reject anything containing a scheme separator or
  // backslash (some browsers normalize "/\evil.com" to "//evil.com").
  if (/^[a-z][a-z0-9+.-]*:/i.test(path)) return false;
  if (path.includes("\\")) return false;
 
  return true;
}
 
/**
 * Picks the redirect target to use after a successful login:
 * prefers the React Router `location.state.from` value (set when we
 * navigate() to the login page in-app), falls back to a `?redirect=`
 * query param (survives a full page refresh on the login page, since
 * router state does not), and finally falls back to `fallback`.
 * Always validated with isSafeInternalRedirect - an unsafe value is
 * treated the same as "no redirect requested".
 */
export function resolveSafeRedirect({ stateFrom, queryRedirect, fallback = "/dashboard" }) {
  if (isSafeInternalRedirect(stateFrom)) return stateFrom;
  if (isSafeInternalRedirect(queryRedirect)) return queryRedirect;
  return fallback;
}
 