import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { GET, POST } from "./route";

const TAG = { id: "tag-1", projectId: "project-1", name: "重要顧客" };

describe("GET /api/tags", () => {
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
    const response = await GET(new Request("http://localhost/api/tags"));
    expect(response.status).toBe(503);
  });

  it("forwards both HISTORY_READ_TOKEN and Authorization headers, same as /api/analysis-runs", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("user-access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tags: [TAG] }), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(new Request("http://localhost/api/tags"));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
    expect(headers.get("Authorization")).toBe("Bearer user-access-token");
  });

  it("forwards the optional projectId query param", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tags: [] }), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(new Request("http://localhost/api/tags?projectId=project-1"));

    const [url] = fetchMock.mock.calls[0];
    expect(url).toContain("projectId=project-1");
  });

  it("returns the tag list on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ tags: [TAG] }), { status: 200 }),
    );

    const response = await GET(new Request("http://localhost/api/tags"));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual({ tags: [TAG] });
  });

  it("forwards a 403 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 403 }));

    const response = await GET(new Request("http://localhost/api/tags"));
    expect(response.status).toBe(403);
  });

  it("returns 502 on an unexpected non-2xx status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await GET(new Request("http://localhost/api/tags"));
    expect(response.status).toBe(502);
  });

  it("returns 503 when the fetch itself throws (network failure)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    const response = await GET(new Request("http://localhost/api/tags"));
    expect(response.status).toBe(503);
  });
});

describe("POST /api/tags", () => {
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

  function makeRequest(body: unknown) {
    return new Request("http://localhost/api/tags", {
      method: "POST",
      body: JSON.stringify(body),
    });
  }

  it("never attaches X-History-Read-Token even when HISTORY_READ_TOKEN is set (JWT-only write)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("user-access-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(TAG), { status: 201 }));
    global.fetch = fetchMock;

    await POST(makeRequest({ projectId: "project-1", name: "重要顧客" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
    expect(headers.get("Authorization")).toBe("Bearer user-access-token");
  });

  it("returns 201 with the created tag on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(TAG), { status: 201 }));

    const response = await POST(makeRequest({ projectId: "project-1", name: "重要顧客" }));
    const body = await response.json();

    expect(response.status).toBe(201);
    expect(body).toEqual(TAG);
  });

  it("forwards a 409 conflict from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "duplicate" }), { status: 409 }),
    );

    const response = await POST(makeRequest({ projectId: "project-1", name: "重要顧客" }));
    expect(response.status).toBe(409);
  });

  it("returns 400 when the request body is not valid JSON", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const response = await POST(
      new Request("http://localhost/api/tags", { method: "POST", body: "not json" }),
    );
    expect(response.status).toBe(400);
  });

  it("forwards a 403 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 403 }));

    const response = await POST(makeRequest({ projectId: "project-1", name: "重要顧客" }));
    expect(response.status).toBe(403);
  });
});
