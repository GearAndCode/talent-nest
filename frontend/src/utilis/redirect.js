// Shared helpers for preserving and validating the "return to this page
// after login" destination used by the Careers -> Login -> Apply flow.
//
// Only ever redirect to internal TalentNest routes. Never trust a raw
// query-string value enough to navigate to it without validation - it is
// attacker-controlled input (an open-redirect vector) if left unchecked.

/**
 * Returns true when `path` is safe to client-side `navigate()` to:
 * a same-origin, absolute app path. Rejects protocol-relative URLs
 * ("//evil.com"), absolute URLs with a scheme ("https://evil.com",
 * "javascript:..."), and backslash tricks browsers sometimes treat as
 * protocol-relative ("/\evil.com").
 */
export function isSafeInternalRedirect(path) {
  if (typeof path !== "string" || path.length === 0) return false;

  // Must be an absolute path within the app.
  if (!path.startsWith("/")) return false;

  // "//host" and "/\host" are both interpreted by browsers as
  // protocol-relative URLs pointing off-site.
  if (path.startsWith("//")) return false;
  if (path.startsWith("/\\")) return false;

  // Reject anything containing an embedded scheme (e.g. a value like
  // "/redirect?to=javascript:alert(1)" or "/..%2f..javascript:...").
  if (/^[a-zA-Z][a-zA-Z0-9+.-]*:/.test(path)) return false;

  return true;
}

/**
 * Builds the login URL for an unauthenticated candidate who tried to act
 * on `targetPath` (e.g. `/candidate/apply/42`). The destination is encoded
 * as a `redirect` query parameter (survives refresh/back-button/sharing
 * the URL) - callers should also pass `state: { from: targetPath }` on
 * navigate() for pages that only look at router state.
 */
export function buildLoginRedirectUrl(loginPath, targetPath) {
  return `${loginPath}?redirect=${encodeURIComponent(targetPath)}`;
}

/**
 * Given the current router `location` (from useLocation()), resolves the
 * safe post-login destination: the `?redirect=` query param first, then
 * `location.state?.from` (used by a few existing pages), falling back to
 * `null` when neither is present or safe.
 */
export function getSafeRedirectFromLocation(location) {
  if (!location) return null;

  const params = new URLSearchParams(location.search || "");
  const fromQuery = params.get("redirect");
  if (fromQuery && isSafeInternalRedirect(fromQuery)) {
    return fromQuery;
  }

  const fromState = location.state?.from;
  if (fromState && isSafeInternalRedirect(fromState)) {
    return fromState;
  }

  return null;
}
