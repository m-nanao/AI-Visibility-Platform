"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useSupabaseSession } from "../lib/supabase/useSupabaseSession";
import {
  AUTH_GUARD_LOADING_TEXT,
  resolveAuthGuardRenderState,
} from "../lib/supabase/session";

// Wraps /history, /history/[id], /history/[id]/report (via
// app/history/layout.tsx) and requires a Supabase Auth session before
// rendering children. This is a separate, additional layer from the
// existing STAGING_ACCESS_CODE gate (proxy.ts, unchanged) — see
// docs/34_supabase_auth_introduction_design.md "5. STAGING_ACCESS_CODEとの
// 関係" for the expected two-step order (staging passcode, then Supabase
// Auth login). backend JWT verification is not implemented yet, so this
// is a frontend-only, UX-level gate — it does not protect the backend
// API directly (docs/34 "6. frontend route保護方針").
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const sessionState = useSupabaseSession();
  const renderState = resolveAuthGuardRenderState(sessionState);
  const router = useRouter();

  useEffect(() => {
    if (renderState.kind === "redirecting") {
      router.replace("/login");
    }
  }, [renderState.kind, router]);

  if (renderState.kind === "loading" || renderState.kind === "redirecting") {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {AUTH_GUARD_LOADING_TEXT}
        </p>
      </div>
    );
  }

  if (renderState.kind === "config-missing") {
    return (
      <div className="mx-auto max-w-5xl px-6 py-8">
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <p>{renderState.message}</p>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}
