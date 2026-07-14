import { createHash } from "node:crypto";

// Shared between proxy.ts (gate) and app/api/staging-auth/route.ts (login).
// Not a real auth system — see docs/09_deployment.md "簡易パスコードガード".
export const STAGING_COOKIE_NAME = "staging_access";

/**
 * The cookie never stores the passcode itself, only this hash, so reading
 * the cookie (e.g. via browser devtools) doesn't reveal the actual code.
 */
export function hashAccessCode(code: string): string {
  return createHash("sha256").update(code).digest("hex");
}

/**
 * Restricts a post-login redirect target to an internal, relative path.
 * Rejects anything that isn't a same-site path (e.g. "//evil.com" or a
 * full URL), which would otherwise be an open-redirect vector since the
 * value round-trips through a query parameter.
 */
export function sanitizeNextPath(value: string | null | undefined): string {
  if (!value) return "/";
  if (!value.startsWith("/") || value.startsWith("//")) return "/";
  return value;
}
