import AuthGuard from "../components/AuthGuard";

// Applies to /history, /history/[id], /history/[id]/report (Next.js
// nested layouts cover all routes under app/history/). This adds a
// Supabase Auth session requirement on top of the existing
// STAGING_ACCESS_CODE gate (proxy.ts, unchanged) — see
// docs/34_supabase_auth_introduction_design.md "5. STAGING_ACCESS_CODEとの
// 関係" / "6. frontend route保護方針".
export default function HistoryLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <AuthGuard>{children}</AuthGuard>;
}
