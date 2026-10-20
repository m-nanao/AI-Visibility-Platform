import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { POST } from "./route";

const RUN_ID = "11111111-1111-1111-1111-111111111111";

function makeRequest(body: unknown = { tagId: "tag-1" }): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/analysis-runs/${RUN_ID}/tags`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: RUN_ID }) },
  ];
}

describe("POST /api/analysis-runs/[id]/tags (attach)", () => {
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
    const response = await POST(...makeRequest());
    expect(response.status).toBe(503);
  });

  it("never attaches X-History-Read-Token (JWT-only write)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    global.fetch = fetchMock;

    await POST(...makeRequest());

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
  });

  it("returns 204 without attempting to parse a body on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));

    const response = await POST(...makeRequest());
    expect(response.status).toBe(204);
    // A 204 Response has a null body — this must not throw.
    await expect(response.text()).resolves.toBe("");
  });

  it("forwards a 409 (queued/running status conflict) as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 409 }));

    const response = await POST(...makeRequest());
    expect(response.status).toBe(409);
  });

  it("forwards a 404 (run or tag not found) as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));

    const response = await POST(...makeRequest());
    expect(response.status).toBe(404);
  });

  it("returns 400 when the request body is not valid JSON", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const response = await POST(
      new Request(`http://localhost/api/analysis-runs/${RUN_ID}/tags`, {
        method: "POST",
        body: "not json",
      }),
      { params: Promise.resolve({ id: RUN_ID }) },
    );
    expect(response.status).toBe(400);
  });

  it("returns 503 when the fetch itself throws", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    const response = await POST(...makeRequest());
    expect(response.status).toBe(503);
  });
});
