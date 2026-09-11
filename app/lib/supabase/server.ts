import { createServerClient, parseCookieHeader } from "@supabase/ssr";
import { getSupabaseConfigStatus } from "./client";

// Server-side Supabase client factory for frontend proxy Route Handlers
// (app/api/analysis-runs/*) — reads the caller's session from the
// incoming Request's Cookie header rather than from Next.js's
// next/headers cookies() API, so this stays a plain function that
// takes a Request and works the same way route.test.ts files already
// call these routes (new Request(...) directly, no Next.js request
// scope needed) — see app/api/analysis-runs/route.test.ts.
//
// Only NEXT_PUBLIC_* env vars are read here, same as client.ts — this
// module must never import a server-only secret
// (SUPABASE_SERVICE_ROLE_KEY / SUPABASE_JWT_SECRET / DATABASE_URL).
// The anon key is the correct key to use here: this client only ever
// reads the *caller's own* session (scoped to whatever cookies their
// browser sent), never acts with elevated privileges, so a service
// role key is neither needed nor appropriate.

function parseCookies(request: Request): { name: string; value: string }[] {
  const header = request.headers.get("cookie");
  if (!header) return [];
  return parseCookieHeader(header);
}

/**
 * Creates a request-scoped Supabase client backed by `request`'s
 * Cookie header. Returns null when NEXT_PUBLIC_SUPABASE_URL /
 * NEXT_PUBLIC_SUPABASE_ANON_KEY aren't set.
 *
 * Read-only for this use case (looking up the current session to
 * forward its access token) — `setAll` is a no-op, since these proxy
 * routes don't need to persist a token refresh back to the browser.
 * The browser's own client (app/lib/supabase/client.ts) already keeps
 * its cookie-based session fresh independently via onAuthStateChange.
 */
export function getSupabaseServerClient(request: Request) {
  const status = getSupabaseConfigStatus();
  if (!status.configured) return null;

  return createServerClient(status.url, status.anonKey, {
    cookies: {
      getAll: () => parseCookies(request),
      setAll: () => {},
    },
  });
}

/**
 * Returns the caller's Supabase Auth access token from `request`'s
 * session cookie, or null when Supabase isn't configured, there is no
 * session, or the lookup fails for any reason. Never throws, never
 * logs the token or any part of it.
 */
export async function getServerSupabaseAccessToken(
  request: Request,
): Promise<string | null> {
  const client = getSupabaseServerClient(request);
  if (!client) return null;

  try {
    const {
      data: { session },
    } = await client.auth.getSession();
    return session?.access_token ?? null;
  } catch {
    return null;
  }
}
