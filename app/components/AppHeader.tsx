"use client";

import Link from "next/link";
import LogoutButton from "./LogoutButton";
import { useSupabaseSession } from "../lib/supabase/useSupabaseSession";

// Shared top bar for every main screen (/, /history, /history/[id],
// /history/[id]/report) — see docs/17_usage_guide.md's navigation
// section. Deliberately NOT rendered on /login or /staging-login (those
// pages are the entry point before there's anywhere to navigate to
// yet). `print:hidden` matches the existing convention on
// /history/[id]/report's own header — navigation chrome has no place
// in a printed report.
//
// This component only *reads* Supabase Auth session state (via the
// existing useSupabaseSession() hook, unchanged) to decide whether to
// show the logout button — it never changes sign-in/sign-out logic
// itself. On "/" (not behind AuthGuard, so a visitor may be signed out
// entirely) this keeps a signed-out visitor from seeing a "ログアウト"
// button that would be confusing to click. On every /history/* page
// (behind AuthGuard — see app/history/layout.tsx) the session is
// already guaranteed signed-in by the time this renders, so the button
// always shows there.
export const APP_HEADER_SERVICE_NAME = "AI Visibility Platform";
export const APP_HEADER_ANALYZE_LINK_TEXT = "分析";
export const APP_HEADER_HISTORY_LINK_TEXT = "履歴";

const NAV_LINK_CLASSNAME =
  "text-sm font-medium text-zinc-600 underline-offset-2 hover:text-zinc-900 hover:underline dark:text-zinc-300 dark:hover:text-zinc-50";

export default function AppHeader() {
  const sessionState = useSupabaseSession();
  const showLogout = sessionState.status === "signed-in";

  return (
    <header className="border-b border-zinc-200 bg-white print:hidden dark:border-zinc-800 dark:bg-zinc-900">
      <div className="mx-auto flex max-w-5xl flex-wrap items-center justify-between gap-x-4 gap-y-2 px-6 py-3">
        <Link
          href="/"
          className="text-base font-semibold text-zinc-900 dark:text-zinc-50"
        >
          {APP_HEADER_SERVICE_NAME}
        </Link>
        <nav className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Link href="/" className={NAV_LINK_CLASSNAME}>
            {APP_HEADER_ANALYZE_LINK_TEXT}
          </Link>
          <Link href="/history" className={NAV_LINK_CLASSNAME}>
            {APP_HEADER_HISTORY_LINK_TEXT}
          </Link>
          {showLogout && <LogoutButton />}
        </nav>
      </div>
    </header>
  );
}
