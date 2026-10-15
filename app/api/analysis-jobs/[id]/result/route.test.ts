import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { GET } from "./route";

function callGet(id = "run-1") {
  return GET(new Request(`http://localhost/api/analysis-jobs/${id}/result`), {
    params: Promise.resolve({ id }),
  });
}

describe("GET /api/analysis-jobs/[id]/result", () => {
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

    const response = await callGet();

    expect(response.status).toBe(503);
  });

  it("forwards the caller's access token as Authorization: Bearer", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("the-access-token");
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 409 }));
    global.fetch = fetchMock;

    await callGet();

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer the-access-token");
  });

  it("never attaches an X-History-Read-Token header", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 409 }));
    global.fetch = fetchMock;

    await callGet();

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
    delete process.env.HISTORY_READ_TOKEN;
  });

  it.each([401, 403, 404, 409, 503])("forwards a %i from the Python API as-is", async (status) => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi
      .fn()
      .mockResolvedValue(new Response(JSON.stringify({ error: "some error" }), { status }));

    const response = await callGet();

    expect(response.status).toBe(status);
  });

  it("returns 502 for an unexpected Python API status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 500 }));

    const response = await callGet();

    expect(response.status).toBe(502);
  });

  it("returns the result on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          analysisRunId: "run-1",
          status: "completed",
          errorMessage: null,
          result: { brandName: "Acme" },
          meta: null,
        }),
        { status: 200 },
      ),
    );

    const response = await callGet();
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body.result).toEqual({ brandName: "Acme" });
  });
});
