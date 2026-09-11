import { describe, expect, it } from "vitest";
import type { Session } from "@supabase/supabase-js";
import {
  deriveSessionState,
  resolveAuthGuardRenderState,
  resolveLoginPageRenderState,
  resolveLoginErrorMessage,
  SUPABASE_CONFIG_MISSING_MESSAGE,
  LOGIN_ERROR_MESSAGE,
  LOGOUT_BUTTON_LABEL,
} from "./session";

function fakeSession(email: string | null): Session {
  return { user: { email } } as unknown as Session;
}

describe("deriveSessionState", () => {
  it("is config-missing when not configured, regardless of session", () => {
    expect(deriveSessionState(false, "loading")).toEqual({ status: "config-missing" });
    expect(deriveSessionState(false, null)).toEqual({ status: "config-missing" });
    expect(deriveSessionState(false, fakeSession("a@example.com"))).toEqual({
      status: "config-missing",
    });
  });

  it("is loading while the initial session check hasn't resolved", () => {
    expect(deriveSessionState(true, "loading")).toEqual({ status: "loading" });
  });

  it("is signed-out when configured but there is no session", () => {
    expect(deriveSessionState(true, null)).toEqual({ status: "signed-out" });
  });

  it("is signed-in with the user's email when a session exists", () => {
    expect(deriveSessionState(true, fakeSession("a@example.com"))).toEqual({
      status: "signed-in",
      email: "a@example.com",
    });
  });

  it("is signed-in with a null email when the session has no email", () => {
    expect(deriveSessionState(true, fakeSession(null))).toEqual({
      status: "signed-in",
      email: null,
    });
  });
});

describe("resolveAuthGuardRenderState", () => {
  it("is loading while the session check is in progress", () => {
    expect(resolveAuthGuardRenderState({ status: "loading" })).toEqual({
      kind: "loading",
    });
  });

  it("is config-missing when Supabase env vars aren't set", () => {
    expect(resolveAuthGuardRenderState({ status: "config-missing" })).toEqual({
      kind: "config-missing",
      message: SUPABASE_CONFIG_MISSING_MESSAGE,
    });
  });

  it("is redirecting when signed out, so the caller can push to /login", () => {
    expect(resolveAuthGuardRenderState({ status: "signed-out" })).toEqual({
      kind: "redirecting",
    });
  });

  it("is authenticated when signed in, so children render", () => {
    expect(
      resolveAuthGuardRenderState({ status: "signed-in", email: "a@example.com" }),
    ).toEqual({ kind: "authenticated" });
  });
});

describe("resolveLoginPageRenderState", () => {
  it("is config-missing when Supabase env vars aren't set", () => {
    expect(resolveLoginPageRenderState({ status: "config-missing" })).toEqual({
      kind: "config-missing",
      message: SUPABASE_CONFIG_MISSING_MESSAGE,
    });
  });

  it("is checking-session while the session check is in progress", () => {
    expect(resolveLoginPageRenderState({ status: "loading" })).toEqual({
      kind: "checking-session",
    });
  });

  it("is redirecting when already signed in, so /login pushes to /history", () => {
    expect(
      resolveLoginPageRenderState({ status: "signed-in", email: "a@example.com" }),
    ).toEqual({ kind: "redirecting" });
  });

  it("is form when signed out, so the login form renders", () => {
    expect(resolveLoginPageRenderState({ status: "signed-out" })).toEqual({
      kind: "form",
    });
  });
});

describe("resolveLoginErrorMessage", () => {
  it("returns the generic Japanese login failure message for any error", () => {
    expect(resolveLoginErrorMessage(new Error("invalid credentials"))).toBe(
      LOGIN_ERROR_MESSAGE,
    );
    expect(resolveLoginErrorMessage(null)).toBe(LOGIN_ERROR_MESSAGE);
    expect(resolveLoginErrorMessage(undefined)).toBe(LOGIN_ERROR_MESSAGE);
  });
});

describe("LOGIN_ERROR_MESSAGE", () => {
  it("is the Japanese login failure message", () => {
    expect(LOGIN_ERROR_MESSAGE).toBe("ログインに失敗しました");
  });
});

describe("SUPABASE_CONFIG_MISSING_MESSAGE", () => {
  it("names both required env vars", () => {
    expect(SUPABASE_CONFIG_MISSING_MESSAGE).toContain("NEXT_PUBLIC_SUPABASE_URL");
    expect(SUPABASE_CONFIG_MISSING_MESSAGE).toContain(
      "NEXT_PUBLIC_SUPABASE_ANON_KEY",
    );
  });
});

describe("LOGOUT_BUTTON_LABEL", () => {
  it("is the Japanese logout button label", () => {
    expect(LOGOUT_BUTTON_LABEL).toBe("ログアウト");
  });
});
