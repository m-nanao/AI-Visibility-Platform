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

  it("forwards a 400 from the Python API as-is (invalid startedFrom/startedTo)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "startedFrom must be a timezone-aware ISO-8601 datetime" }),
        { status: 400 },
      ),
    );

    const response = await GET(makeRequest("?startedFrom=not-a-date"));

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({
      error: "startedFrom must be a timezone-aware ISO-8601 datetime",
    });
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

  // --- Query param forwarding (feature/history-server-side-search-pagination) ---

  it("forwards limit/offset as before", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 40, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest("?limit=20&offset=40"));

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.get("limit")).toBe("20");
    expect(forwardedParams.get("offset")).toBe("40");
  });

  it("forwards search/important/startedFrom/startedTo/sort when present", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(
      makeRequest(
        "?search=cybozu&important=true&startedFrom=2026-03-01T00%3A00%3A00%2B09%3A00&startedTo=2026-03-06T00%3A00%3A00%2B09%3A00&sort=oldest",
      ),
    );

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.get("search")).toBe("cybozu");
    expect(forwardedParams.get("important")).toBe("true");
    expect(forwardedParams.get("startedFrom")).toBe("2026-03-01T00:00:00+09:00");
    expect(forwardedParams.get("startedTo")).toBe("2026-03-06T00:00:00+09:00");
    expect(forwardedParams.get("sort")).toBe("oldest");
  });

  it("omits search/important/startedFrom/startedTo/sort entirely when the caller didn't set them", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.has("search")).toBe(false);
    expect(forwardedParams.has("important")).toBe(false);
    expect(forwardedParams.has("startedFrom")).toBe(false);
    expect(forwardedParams.has("startedTo")).toBe(false);
    expect(forwardedParams.has("sort")).toBe(false);
  });

  // --- AI observation filter forwarding (feature/history-ai-observation-filter) ---

  it("forwards aiOverviewObservation/chatgptObservation/claudeObservation/geminiObservation when present", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(
      makeRequest(
        "?aiOverviewObservation=mentioned&chatgptObservation=not_mentioned&claudeObservation=off&geminiObservation=unavailable",
      ),
    );

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.get("aiOverviewObservation")).toBe("mentioned");
    expect(forwardedParams.get("chatgptObservation")).toBe("not_mentioned");
    expect(forwardedParams.get("claudeObservation")).toBe("off");
    expect(forwardedParams.get("geminiObservation")).toBe("unavailable");
  });

  it("omits the 4 AI observation filter params entirely when the caller didn't set them", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.has("aiOverviewObservation")).toBe(false);
    expect(forwardedParams.has("chatgptObservation")).toBe(false);
    expect(forwardedParams.has("claudeObservation")).toBe(false);
    expect(forwardedParams.has("geminiObservation")).toBe(false);
  });

  // --- favorite forwarding (feature/history-favorite-flag) ---

  it("forwards favorite=true when present", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest("?favorite=true"));

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.get("favorite")).toBe("true");
  });

  it("omits favorite entirely when the caller didn't set it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ items: [], limit: 20, offset: 0, total: 0 }), {
        status: 200,
      }),
    );
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [url] = fetchMock.mock.calls[0];
    const forwardedParams = new URL(url as string).searchParams;
    expect(forwardedParams.has("favorite")).toBe(false);
  });
});
