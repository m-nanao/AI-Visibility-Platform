import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { GET } from "./route";

function makeRequest(): Request {
  return new Request("http://localhost/api/me/projects");
}

describe("GET /api/me/projects", () => {
  const originalApiUrl = process.env.PYTHON_ANALYSIS_API_URL;
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
    getServerSupabaseAccessTokenMock.mockReset().mockResolvedValue(null);
  });

  afterEach(() => {
    if (originalApiUrl === undefined) delete process.env.PYTHON_ANALYSIS_API_URL;
    else process.env.PYTHON_ANALYSIS_API_URL = originalApiUrl;
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns 503 when PYTHON_ANALYSIS_API_URL is unset", async () => {
    delete process.env.PYTHON_ANALYSIS_API_URL;

    const response = await GET(makeRequest());

    expect(response.status).toBe(503);
  });

  it("returns 503 when the Python API request fails outright", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    const response = await GET(makeRequest());

    expect(response.status).toBe(503);
  });

  it("forwards the caller's access token as Authorization: Bearer", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("the-access-token");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ projects: [] }), { status: 200 }));
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer the-access-token");
  });

  it("never attaches an X-History-Read-Token header — this endpoint has no such fallback", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ projects: [] }), { status: 200 }));
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
    delete process.env.HISTORY_READ_TOKEN;
  });

  it("sends no Authorization header when there is no session", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ projects: [] }), { status: 200 }));
    global.fetch = fetchMock;

    await GET(makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("forwards a 401 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi
      .fn()
      .mockResolvedValue(
        new Response(JSON.stringify({ error: "authentication required" }), { status: 401 }),
      );

    const response = await GET(makeRequest());

    expect(response.status).toBe(401);
  });

  it("returns 502 when the Python API returns an unexpected status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));

    const response = await GET(makeRequest());

    expect(response.status).toBe(502);
  });

  it("returns 502 when the Python API response fails schema validation", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ projects: "not-an-array" }), { status: 200 }));

    const response = await GET(makeRequest());

    expect(response.status).toBe(502);
  });

  it("returns the project list on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ projects: [{ id: "project-a" }] }), { status: 200 }),
    );

    const response = await GET(makeRequest());
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ projects: [{ id: "project-a" }] });
  });

  it("never includes the caller's access token in the response returned", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("super-secret-token");
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ projects: [] }), { status: 200 }));

    const response = await GET(makeRequest());
    const text = await response.text();

    expect(text).not.toContain("super-secret-token");
  });
});
