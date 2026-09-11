"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useSupabaseSession } from "../lib/supabase/useSupabaseSession";
import { getSupabaseBrowserClient } from "../lib/supabase/client";
import {
  LOGIN_PAGE_TITLE,
  LOGIN_EMAIL_LABEL,
  LOGIN_PASSWORD_LABEL,
  LOGIN_BUTTON_LABEL,
  LOGIN_BUTTON_LOADING_LABEL,
  LOGIN_CHECKING_SESSION_TEXT,
  resolveLoginPageRenderState,
  resolveLoginErrorMessage,
} from "../lib/supabase/session";

// Email + Password login for Supabase Auth (initial recommendation,
// docs/34_supabase_auth_introduction_design.md "5. 推奨ログイン方式").
// This page itself doesn't handle the STAGING_ACCESS_CODE passcode —
// that gate (proxy.ts) runs first and is unaffected by this page; see
// docs/34 "5. STAGING_ACCESS_CODEとの関係" for the expected order
// (staging passcode -> this login -> /history).
export default function LoginPage() {
  const sessionState = useSupabaseSession();
  const renderState = resolveLoginPageRenderState(sessionState);
  const router = useRouter();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  useEffect(() => {
    if (renderState.kind === "redirecting") {
      router.replace("/history");
    }
  }, [renderState.kind, router]);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const client = getSupabaseBrowserClient();
    if (!client) return;

    setSubmitting(true);
    setErrorMessage(null);

    const { error } = await client.auth.signInWithPassword({ email, password });

    setSubmitting(false);
    if (error) {
      setErrorMessage(resolveLoginErrorMessage(error));
      return;
    }

    router.push("/history");
  }

  if (renderState.kind === "config-missing") {
    return (
      <div className="mx-auto flex min-h-full max-w-sm flex-1 flex-col justify-center gap-4 px-6 py-12">
        <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
          <p>{renderState.message}</p>
        </div>
      </div>
    );
  }

  if (renderState.kind === "checking-session" || renderState.kind === "redirecting") {
    return (
      <div className="mx-auto flex min-h-full max-w-sm flex-1 flex-col justify-center gap-4 px-6 py-12">
        <p className="text-sm text-zinc-500 dark:text-zinc-400">
          {LOGIN_CHECKING_SESSION_TEXT}
        </p>
      </div>
    );
  }

  return (
    <div className="mx-auto flex min-h-full max-w-sm flex-1 flex-col justify-center gap-4 px-6 py-12">
      <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
        {LOGIN_PAGE_TITLE}
      </h1>

      <form onSubmit={handleSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
          {LOGIN_EMAIL_LABEL}
          <input
            type="email"
            name="email"
            required
            autoFocus
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          />
        </label>

        <label className="flex flex-col gap-1 text-sm text-zinc-700 dark:text-zinc-300">
          {LOGIN_PASSWORD_LABEL}
          <input
            type="password"
            name="password"
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          />
        </label>

        {errorMessage && (
          <p className="text-sm text-rose-600 dark:text-rose-400">{errorMessage}</p>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="inline-flex h-10 items-center justify-center rounded-md bg-zinc-900 px-5 text-sm font-medium text-white transition-colors hover:bg-zinc-700 disabled:opacity-60 dark:bg-zinc-50 dark:text-zinc-900 dark:hover:bg-zinc-300"
        >
          {submitting ? LOGIN_BUTTON_LOADING_LABEL : LOGIN_BUTTON_LABEL}
        </button>
      </form>
    </div>
  );
}
