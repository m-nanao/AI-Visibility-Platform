import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GET } from "./route";

function makeRequest(id: string): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/analysis-runs/${id}`),
    { params: Promise.resolve({ id }) },
  ];
}

describe("GET /api/analysis-runs/[id]", () => {
  const originalApiUrl = process.env.PYTHON_ANALYSIS_API_URL;
  const originalToken = process.env.HISTORY_READ_TOKEN;
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
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

  it("attaches HISTORY_READ_TOKEN as the X-History-Read-Token header when set", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
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
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
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

  it("still forwards a 404 from the Python API as before", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "analysis run not found" }), { status: 404 }),
    );

    const response = await GET(...makeRequest("11111111-1111-1111-1111-111111111111"));

    expect(response.status).toBe(404);
    expect(await response.json()).toEqual({ error: "analysis run not found" });
  });
});
