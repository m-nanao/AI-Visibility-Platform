import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { POST } from "./route";

function makeRequest(body: unknown): Request {
  return new Request("http://localhost/api/analysis-jobs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

const VALID_BODY = {
  projectId: "project-1",
  idempotencyKey: "key-1",
  brandName: "Acme",
  urls: ["https://example.com"],
};

describe("POST /api/analysis-jobs", () => {
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

    const response = await POST(makeRequest(VALID_BODY));

    expect(response.status).toBe(503);
  });

  it("returns 400 when the request body isn't valid JSON", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const request = new Request("http://localhost/api/analysis-jobs", {
      method: "POST",
      body: "not json",
    });

    const response = await POST(request);

    expect(response.status).toBe(400);
  });

  it("returns 503 when the Python API request fails outright (never fabricates a result)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    const response = await POST(makeRequest(VALID_BODY));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body.error).toBeTypeOf("string");
    expect(body.analysisRunId).toBeUndefined();
  });

  it("forwards the caller's access token as Authorization: Bearer", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("the-access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ analysisRunId: "run-1", status: "queued" }), {
        status: 202,
      }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest(VALID_BODY));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer the-access-token");
  });

  it("never attaches an X-History-Read-Token header", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ analysisRunId: "run-1", status: "queued" }), {
        status: 202,
      }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest(VALID_BODY));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
    delete process.env.HISTORY_READ_TOKEN;
  });

  it.each([400, 401, 403, 404, 409, 429, 503])(
    "forwards a %i from the Python API as-is",
    async (status) => {
      process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
      global.fetch = vi
        .fn()
        .mockResolvedValue(new Response(JSON.stringify({ error: "some error" }), { status }));

      const response = await POST(makeRequest(VALID_BODY));

      expect(response.status).toBe(status);
    },
  );

  it("returns 502 for an unexpected Python API status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));

    const response = await POST(makeRequest(VALID_BODY));

    expect(response.status).toBe(502);
  });

  it("returns 202 with the accepted job on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ analysisRunId: "run-1", status: "queued" }), {
        status: 202,
      }),
    );

    const response = await POST(makeRequest(VALID_BODY));
    const body = await response.json();

    expect(response.status).toBe(202);
    expect(body).toEqual({ analysisRunId: "run-1", status: "queued" });
  });

  it("never includes the caller's access token in the response returned", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("super-secret-token");
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ analysisRunId: "run-1", status: "queued" }), {
        status: 202,
      }),
    );

    const response = await POST(makeRequest(VALID_BODY));
    const text = await response.text();

    expect(text).not.toContain("super-secret-token");
  });
});
