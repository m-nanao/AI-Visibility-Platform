import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { GET } from "./route";

function makeRequest(query = ""): Request {
  return new Request(`http://localhost/api/analysis-runs${query}`);
}

describe("GET /api/analysis-runs", () => {
  const originalApiUrl = process.env.PYTHON_ANALYSIS_API_URL;
  const originalToken = process.env.HISTORY_READ_TOKEN;
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    getServerSupabaseAccessTokenMock.mockReset().mockResolvedValue(null);
  });

  afterEach(() => {
    if (originalApiUrl === undefined) delete process.env.PYTHON_ANALYSIS_API_URL;
    else process.env.PYTHON_ANALYSIS_API_URL = originalApiUrl;
    if (originalToken === undefined) delete process.env.HISTORY_READ_TOKEN;
    else process.env.HISTORY_READ_TOKEN = originalToken;
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns 503 when PYTHON_ANALYSIS_API_URL is unset", async () => {
    delete process.env.PYTHON_ANALYSIS_API_URL;

    const response = await GET(makeRequest());

    expect(response.status).toBe(503);
  });

  it("attaches HISTORY_READ_TOKEN as the X-History-Read-Token header when set", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: null }), {
          status: 200,
        }),
      );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
  });

  it("sends no X-History-Read-Token header when HISTORY_READ_TOKEN is unset", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    delete process.env.HISTORY_READ_TOKEN;
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis history read token is not configured" }), {
        status: 503,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
  });

  it("never includes the token in the response returned to the caller", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: null }), {
        status: 200,
      }),
    );

    const response = await GET(makeRequest());
    const text = await response.text();

    expect(text).not.toContain("shared-secret-token");
  });

  it("forwards a 403 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis history read access denied" }), {
        status: 403,
      }),
    );

    const response = await GET(makeRequest());

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "analysis history read access denied" });
  });

  it("still forwards a 503 from the Python API as before (disabled behavior unchanged)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis history read API is not enabled" }), {
        status: 503,
      }),
    );

    const response = await GET(makeRequest());

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "analysis history read API is not enabled" });
  });

  // --- Supabase access token forwarding (frontend proxy -> backend) --------

  it("attaches Authorization: Bearer <token> when a Supabase access token is available", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("supabase-access-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: null }), {
          status: 200,
        }),
      );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer supabase-access-token");
    // HISTORY_READ_TOKEN must still be sent alongside it.
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
  });

  it("sends no Authorization header when there is no Supabase access token", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue(null);
    const fetchMock = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: null }), {
          status: 200,
        }),
      );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("Authorization")).toBe(false);
    // HISTORY_READ_TOKEN gate must be unaffected either way.
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
  });

  it("never includes the Supabase access token in the response returned to the caller", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("supabase-access-token");
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: null }), {
        status: 200,
      }),
    );

    const response = await GET(makeRequest());
    const text = await response.text();

    expect(text).not.toContain("supabase-access-token");
  });
});
