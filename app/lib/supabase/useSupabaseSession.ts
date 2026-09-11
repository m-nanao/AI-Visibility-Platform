"use client";

import { useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { getSupabaseBrowserClient, getSupabaseConfigStatus } from "./client";
import { deriveSessionState, type SessionState } from "./session";

/**
 * Resolves the current Supabase Auth session state for a client
 * component. Branching logic lives in deriveSessionState() (see
 * session.ts) so it stays unit-testable — this hook itself is only
 * wiring and isn't unit-tested directly, the same convention as
 * app/history/page.tsx's data-fetching useEffect.
 */
export function useSupabaseSession(): SessionState {
  const configured = getSupabaseConfigStatus().configured;
  const [session, setSession] = useState<Session | null | "loading">("loading");

  useEffect(() => {
    if (!configured) return;
    const client = getSupabaseBrowserClient();
    if (!client) return;

    let cancelled = false;

    client.auth.getSession().then(({ data }) => {
      if (!cancelled) setSession(data.session);
    });

    const {
      data: { subscription },
    } = client.auth.onAuthStateChange((_event, newSession) => {
      if (!cancelled) setSession(newSession);
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, [configured]);

  return deriveSessionState(configured, session);
}
