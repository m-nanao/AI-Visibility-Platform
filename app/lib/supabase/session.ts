import type { Session } from "@supabase/supabase-js";

// Pure view-state types/resolvers shared by useSupabaseSession.ts,
// app/components/AuthGuard.tsx, and app/login/page.tsx. Kept separate
// from the hook itself (which touches the actual Supabase client) so
// the branching logic is unit-testable without rendering any JSX or a
// DOM — this project's vitest run has no jsdom environment, the same
// convention used for app/lib/analysis-history.ts's resolveHistoryFetchOutcome().

export type SessionState =
  | { status: "loading" }
  | { status: "config-missing" }
  | { status: "signed-in"; email: string | null }
  | { status: "signed-out" };

/**
 * Turns the raw inputs (env configured?, current Supabase session) into
 * the SessionState the rest of the UI branches on. `session` is the
 * literal string "loading" while the initial `auth.getSession()` call
 * hasn't resolved yet.
 */
export function deriveSessionState(
  configured: boolean,
  session: Session | null | "loading",
): SessionState {
  if (!configured) return { status: "config-missing" };
  if (session === "loading") return { status: "loading" };
  if (session) return { status: "signed-in", email: session.user?.email ?? null };
  return { status: "signed-out" };
}

export const SUPABASE_CONFIG_MISSING_MESSAGE =
  "Supabase Authの設定が未完了です。NEXT_PUBLIC_SUPABASE_URL / NEXT_PUBLIC_SUPABASE_ANON_KEY を設定してください。";

// --- AuthGuard (app/components/AuthGuard.tsx) ---

export type AuthGuardRenderState =
  | { kind: "loading" }
  | { kind: "config-missing"; message: string }
  | { kind: "redirecting" }
  | { kind: "authenticated" };

export const AUTH_GUARD_LOADING_TEXT = "ログイン状態を確認しています...";

/**
 * Decides what AuthGuard should render for a given SessionState.
 * "redirecting" covers signed-out — AuthGuard reacts to this by pushing
 * to /login (see docs/34_supabase_auth_introduction_design.md "6.
 * frontend route保護方針").
 */
export function resolveAuthGuardRenderState(
  sessionState: SessionState,
): AuthGuardRenderState {
  switch (sessionState.status) {
    case "loading":
      return { kind: "loading" };
    case "config-missing":
      return { kind: "config-missing", message: SUPABASE_CONFIG_MISSING_MESSAGE };
    case "signed-out":
      return { kind: "redirecting" };
    case "signed-in":
      return { kind: "authenticated" };
  }
}

// --- Login page (app/login/page.tsx) ---

export type LoginPageRenderState =
  | { kind: "config-missing"; message: string }
  | { kind: "checking-session" }
  | { kind: "redirecting" }
  | { kind: "form" };

export const LOGIN_PAGE_TITLE = "ログイン";
export const LOGIN_EMAIL_LABEL = "メールアドレス";
export const LOGIN_PASSWORD_LABEL = "パスワード";
export const LOGIN_BUTTON_LABEL = "ログイン";
export const LOGIN_BUTTON_LOADING_LABEL = "ログイン中...";
export const LOGIN_ERROR_MESSAGE = "ログインに失敗しました";
export const LOGIN_CHECKING_SESSION_TEXT = "ログイン状態を確認しています...";

/**
 * Already-signed-in visitors are redirected away from /login to
 * /history rather than being shown the form again.
 */
export function resolveLoginPageRenderState(
  sessionState: SessionState,
): LoginPageRenderState {
  switch (sessionState.status) {
    case "config-missing":
      return { kind: "config-missing", message: SUPABASE_CONFIG_MISSING_MESSAGE };
    case "loading":
      return { kind: "checking-session" };
    case "signed-in":
      return { kind: "redirecting" };
    case "signed-out":
      return { kind: "form" };
  }
}

/**
 * Maps any signInWithPassword() failure to a single generic Japanese
 * message. Takes the error (currently unused) so a more specific
 * mapping can be added later without changing the call site in
 * app/login/page.tsx.
 */
export function resolveLoginErrorMessage(error: unknown): string {
  void error;
  return LOGIN_ERROR_MESSAGE;
}

// --- Logout (app/components/LogoutButton.tsx) ---

export const LOGOUT_BUTTON_LABEL = "ログアウト";
