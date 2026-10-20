import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { DELETE, PATCH } from "./route";

const TAG_ID = "tag-1";
const TAG = { id: TAG_ID, projectId: "project-1", name: "重要顧客（改名後）" };

function makePatchArgs(body: unknown): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/tags/${TAG_ID}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
    { params: Promise.resolve({ id: TAG_ID }) },
  ];
}

function makeDeleteArgs(): [Request, { params: Promise<{ id: string }> }] {
  return [
    new Request(`http://localhost/api/tags/${TAG_ID}`, { method: "DELETE" }),
    { params: Promise.resolve({ id: TAG_ID }) },
  ];
}

describe("PATCH /api/tags/[id]", () => {
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

  it("never attaches X-History-Read-Token (JWT-only write)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    process.env.HISTORY_READ_TOKEN = "shared-secret-token";
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(TAG), { status: 200 }));
    global.fetch = fetchMock;

    await PATCH(...makePatchArgs({ name: "重要顧客（改名後）" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("X-History-Read-Token")).toBe(false);
  });

  it("returns the renamed tag on success", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(TAG), { status: 200 }));

    const response = await PATCH(...makePatchArgs({ name: "重要顧客（改名後）" }));
    const body = await response.json();

    expect(response.status).toBe(200);
    expect(body).toEqual(TAG);
  });

  it("forwards a 404 as-is (tag not found)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));

    const response = await PATCH(...makePatchArgs({ name: "x" }));
    expect(response.status).toBe(404);
  });

  it("forwards a 409 conflict as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 409 }));

    const response = await PATCH(...makePatchArgs({ name: "x" }));
    expect(response.status).toBe(409);
  });
});

describe("DELETE /api/tags/[id]", () => {
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

  it("returns a success body (not an error) when the Python API returns 200", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ deleted: true }), { status: 200 }),
    );

    const response = await DELETE(...makeDeleteArgs());
    expect(response.status).toBe(200);
  });

  it("forwards a 404 as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 404 }));

    const response = await DELETE(...makeDeleteArgs());
    expect(response.status).toBe(404);
  });

  it("forwards a 403 as-is", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 403 }));

    const response = await DELETE(...makeDeleteArgs());
    expect(response.status).toBe(403);
  });
});
