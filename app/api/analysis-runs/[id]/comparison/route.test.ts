import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { GET } from "./route";

const SAMPLE_COMPARISON = {
  current: {
    id: "11111111-1111-1111-1111-111111111111",
    startedAt: "2026-09-10T00:00:00+09:00",
    visibilityScore: 91,
  },
  previous: {
    id: "22222222-2222-2222-2222-222222222222",
    startedAt: "2026-09-01T00:00:00+09:00",
    visibilityScore: 86,
  },
  diff: {
    visibilityScore: { current: 91, previous: 86, delta: 5 },
    cooccurrence: { topN: 10, newTerms: [], removedTerms: [], changedTerms: [] },
    improvements: { currentCount: 4, previousCount: 3, delta: 1 },
  },
  warnings: [],
};

function makeRequest(id: string): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/analysis-runs/${id}/comparison`),
    { params: Promise.resolve({ id }) },
  ];
}

describe("GET /api/analysis-runs/[id]/comparison", () => {
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

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(503);
  });

  it("requests the /comparison path on the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    const [url] = fetchMock.mock.calls[0];
    expect(url).toBe(
      "http://python-api.test/analysis-runs/11111111-1111-1111-1111-111111111111/comparison",
    );
  });

  it("attaches HISTORY_READ_TOKEN as the X-History-Read-Token header when set", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

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

    await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
  });

  it("never includes the token in the response returned to the caller", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));
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

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(403);
    expect(await response.json()).toEqual({ error: "analysis history read access denied" });
  });

  it("forwards a 503 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis history read API is not enabled" }), {
        status: 503,
      }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ error: "analysis history read API is not enabled" });
  });

  it("forwards a 404 from the Python API as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "analysis run not found" });
  });

  it("returns 200 with previous:null/diff:null passed through when there is no earlier run", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const noPrevious = {
      current: SAMPLE_COMPARISON.current,
      previous: null,
      diff: null,
      warnings: ["比較できる過去履歴がまだありません。"],
    };
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(noPrevious), { status: 200 }));

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.previous).toBeNull();
    expect(body.diff).toBeNull();
  });

  it("returns 200 with the parsed comparison when a previous run exists", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(200);
    const body = await response.json();
    expect(body.diff.visibilityScore.delta).toBe(5);
  });

  it("returns 502 when the Python API response fails schema validation", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ not: "valid" }), { status: 200 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(502);
  });

  // --- Supabase access token forwarding (frontend proxy -> backend) --------

  it("attaches Authorization: Bearer <token> when a Supabase access token is available", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("supabase-access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer supabase-access-token");
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
  });

  it("sends no Authorization header when there is no Supabase access token", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue(null);
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );
    global.fetch = fetchMock;

    await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("Authorization")).toBe(false);
    expect(headers.get("X-History-Read-Token")).toBe("shared-secret-token");
  });

  it("never includes the Supabase access token in the response returned to the caller", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    getServerSupabaseAccessTokenMock.mockResolvedValue("supabase-access-token");
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(SAMPLE_COMPARISON), { status: 200 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));
    const text = await response.text();

    expect(text).not.toContain("supabase-access-token");
  });
});
