"use client";

import { useRouter } from "next/navigation";
import { getSupabaseBrowserClient } from "../lib/supabase/client";
import { LOGOUT_BUTTON_LABEL } from "../lib/supabase/session";

// Placed on /history (see app/history/page.tsx). Signs out of Supabase
// Auth only — the existing STAGING_ACCESS_CODE cookie (proxy.ts) is
// untouched, so a signed-out visitor still needs the staging passcode
// again only if that cookie separately expires.
export default function LogoutButton() {
  const router = useRouter();

  async function handleLogout() {
    const client = getSupabaseBrowserClient();
    if (client) {
      await client.auth.signOut();
    }
    router.push("/login");
  }

  return (
    <button
      type="button"
      onClick={handleLogout}
      className="rounded-md border border-zinc-300 px-3 py-1.5 text-sm font-medium text-zinc-700 hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-800"
    >
      {LOGOUT_BUTTON_LABEL}
    </button>
  );
}
