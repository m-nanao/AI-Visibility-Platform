import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { POST } from "./route";

function makeRequest(id: string): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/analysis-runs/${id}/web-ai-gap/ai-comparison`, {
      method: "POST",
    }),
    { params: Promise.resolve({ id }) },
  ];
}

const RUN_ID = "11111111-1111-1111-1111-111111111111";

const SUCCESS_BODY = {
  analysisRunId: RUN_ID,
  webAiGapAiComparison: {
    status: "real",
    method: "ai_comparison",
    matchedPoints: ["matched"],
    webStrongAiWeak: ["web strong"],
    aiStrongWebWeak: ["ai strong"],
    gapSummary: "gap",
    recommendations: ["recommend"],
    caution: "AIによる比較であり、AIの内部認識を直接示すものではありません。",
  },
};

describe("POST /api/analysis-runs/[id]/web-ai-gap/ai-comparison", () => {
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

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(503);
  });

  it("attaches HISTORY_READ_TOKEN as the X-History-Read-Token header when set", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
    );
    global.fetch = fetchMock;

    await POST(...makeRequest(RUN_ID));

    const [url, requestInit] = fetchMock.mock.calls[0];
    expect(url).toBe(`http://python-api.test/analysis-runs/${RUN_ID}/web-ai-gap/ai-comparison`);
    expect(requestInit.method).toBe("POST");
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

    await POST(...makeRequest(RUN_ID));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
  });

  it("attaches the caller's Supabase access token as Authorization: Bearer when present", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("user-access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SUCCESS_BODY), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(...makeRequest(RUN_ID));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer user-access-token");
  });

  it("never includes the HISTORY_READ_TOKEN value in the response returned to the caller", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SUCCESS_BODY), { status: 200 }),
    );

    const response = await POST(...makeRequest(RUN_ID));
    const text = await response.text();

    expect(text).not.toContain("shared-secret-token");
  });

  it("forwards a 403 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis history read access denied" }), {
        status: 403,
      }),
    );

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(403);
  });

  it("forwards a 404 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
    );

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(404);
  });

  it("forwards a 503 from the Python API with its own reason text (not even attempted)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "Anthropic API key is not configured." }), {
        status: 503,
      }),
    );

    const response = await POST(...makeRequest(RUN_ID));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: "Anthropic API key is not configured." });
  });

  it("forwards a 502 from the Python API with its own reason text (call attempted and failed)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "Anthropic API request failed with HTTP 500." }), {
        status: 502,
      }),
    );

    const response = await POST(...makeRequest(RUN_ID));
    const body = await response.json();

    expect(response.status).toBe(502);
    expect(body).toEqual({ error: "Anthropic API request failed with HTTP 500." });
  });

  it("returns 502 with a generic message for an unexpected non-2xx status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(502);
  });

  it("returns 502 when the Python API returns invalid JSON on success status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("not json", { status: 200 }));

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(502);
  });

  it("returns 503 when the fetch itself throws (network failure)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("network down"));

    const response = await POST(...makeRequest(RUN_ID));

    expect(response.status).toBe(503);
  });

  it("forwards the Python API's success body as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SUCCESS_BODY), { status: 200 }),
    );

    const response = await POST(...makeRequest(RUN_ID));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(SUCCESS_BODY);
  });
});
