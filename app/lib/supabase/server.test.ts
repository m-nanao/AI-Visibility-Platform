import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getSessionMock = vi.fn();
const createServerClientMock = vi.fn(() => ({
  auth: { getSession: getSessionMock },
}));

vi.mock("@supabase/ssr", () => ({
  createServerClient: (...args: unknown[]) => createServerClientMock(...args),
  parseCookieHeader: (header: string) =>
    header
      .split(";")
      .map((part) => part.trim())
      .filter(Boolean)
      .map((part) => {
        const [name, ...rest] = part.split("=");
        return { name, value: rest.join("=") };
      }),
}));

import { getServerSupabaseAccessToken, getSupabaseServerClient } from "./server";

function makeRequest(cookieHeader?: string): Request {
  return new Request("http://localhost/api/analysis-runs", {
    headers: cookieHeader ? { cookie: cookieHeader } : {},
  });
}

describe("getSupabaseServerClient / getServerSupabaseAccessToken", () => {
  const originalUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const originalAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  beforeEach(() => {
    getSessionMock.mockReset();
    createServerClientMock.mockClear();
  });

  afterEach(() => {
    if (originalUrl === undefined) {
      delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    } else {
      process.env.NEXT_PUBLIC_SUPABASE_URL = originalUrl;
    }
    if (originalAnonKey === undefined) {
      delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
    } else {
      process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = originalAnonKey;
    }
  });

  function configureEnv() {
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://example.supabase.co";
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY = "anon-key";
  }

  function clearEnv() {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  }

  it("getSupabaseServerClient returns null when Supabase isn't configured", () => {
    clearEnv();

    expect(getSupabaseServerClient(makeRequest())).toBeNull();
    expect(createServerClientMock).not.toHaveBeenCalled();
  });

  it("getServerSupabaseAccessToken returns null when Supabase isn't configured", async () => {
    clearEnv();

    await expect(getServerSupabaseAccessToken(makeRequest())).resolves.toBeNull();
    expect(createServerClientMock).not.toHaveBeenCalled();
  });

  it("getServerSupabaseAccessToken returns null when there is no session", async () => {
    configureEnv();
    getSessionMock.mockResolvedValue({ data: { session: null } });

    await expect(
      getServerSupabaseAccessToken(makeRequest("sb-example-auth-token=abc")),
    ).resolves.toBeNull();
  });

  it("getServerSupabaseAccessToken returns the session's access token", async () => {
    configureEnv();
    getSessionMock.mockResolvedValue({
      data: { session: { access_token: "real-access-token" } },
    });

    await expect(
      getServerSupabaseAccessToken(makeRequest("sb-example-auth-token=abc")),
    ).resolves.toBe("real-access-token");
  });

  it("getServerSupabaseAccessToken returns null when the session lookup throws", async () => {
    configureEnv();
    getSessionMock.mockRejectedValue(new Error("network error"));

    await expect(getServerSupabaseAccessToken(makeRequest())).resolves.toBeNull();
  });

  it("passes the request's parsed cookies to the Supabase client's getAll()", () => {
    configureEnv();

    getSupabaseServerClient(makeRequest("foo=bar; baz=qux"));

    const options = createServerClientMock.mock.calls[0][2] as {
      cookies: { getAll: () => { name: string; value: string }[] };
    };
    expect(options.cookies.getAll()).toEqual([
      { name: "foo", value: "bar" },
      { name: "baz", value: "qux" },
    ]);
  });

  it("returns an empty cookie list when the request has no Cookie header", () => {
    configureEnv();

    getSupabaseServerClient(makeRequest());

    const options = createServerClientMock.mock.calls[0][2] as {
      cookies: { getAll: () => { name: string; value: string }[] };
    };
    expect(options.cookies.getAll()).toEqual([]);
  });

  it("never logs the access token", async () => {
    configureEnv();
    getSessionMock.mockResolvedValue({
      data: { session: { access_token: "super-secret-token" } },
    });
    const logSpy = vi.spyOn(console, "log").mockImplementation(() => {});
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    await getServerSupabaseAccessToken(makeRequest());

    expect(logSpy).not.toHaveBeenCalled();
    expect(warnSpy).not.toHaveBeenCalled();
    logSpy.mockRestore();
    warnSpy.mockRestore();
  });
});
