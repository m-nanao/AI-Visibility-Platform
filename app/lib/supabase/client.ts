import { createBrowserClient } from "@supabase/ssr";
import type { SupabaseClient } from "@supabase/supabase-js";

// Browser-side Supabase client factory. This file must only ever read
// NEXT_PUBLIC_* env vars — it runs in the browser, so a server-only
// secret (SUPABASE_SERVICE_ROLE_KEY / SUPABASE_JWT_SECRET / DATABASE_URL)
// must never be imported or referenced here. See
// docs/34_supabase_auth_introduction_design.md "10. 必要env案".
//
// Uses @supabase/ssr's createBrowserClient() (not
// @supabase/supabase-js's createClient() directly) so the session is
// persisted via cookies instead of only localStorage — a Next.js
// server Route Handler has no access to the browser's localStorage,
// but it can read the request's Cookie header (see
// app/lib/supabase/server.ts). The returned client has the same
// SupabaseClient API/type either way, so nothing else in this app
// (useSupabaseSession.ts, /login, AuthGuard, LogoutButton) needed to
// change.

export type SupabaseConfigStatus =
  | { configured: true; url: string; anonKey: string }
  | { configured: false };

export function getSupabaseConfigStatus(): SupabaseConfigStatus {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) {
    return { configured: false };
  }
  return { configured: true, url, anonKey };
}

let cachedClient: SupabaseClient | null = null;

/**
 * Lazily creates (and caches) the browser Supabase client. Returns null
 * instead of throwing when NEXT_PUBLIC_SUPABASE_URL /
 * NEXT_PUBLIC_SUPABASE_ANON_KEY aren't set, so callers (useSupabaseSession,
 * /login) can show a config-missing message rather than crashing the page
 * or failing the build.
 */
export function getSupabaseBrowserClient(): SupabaseClient | null {
  const status = getSupabaseConfigStatus();
  if (!status.configured) return null;
  if (!cachedClient) {
    cachedClient = createBrowserClient(status.url, status.anonKey);
  }
  return cachedClient;
}
