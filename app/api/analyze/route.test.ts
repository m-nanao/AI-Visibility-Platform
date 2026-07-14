import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { POST } from "./route";
import { buildDummyAnalysis } from "../../lib/dummy-data";

function makeRequest(body: unknown) {
  return new Request("http://localhost/api/analyze", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

function pythonMetaOverride(
  overrides: Partial<ReturnType<typeof buildDummyAnalysis>["meta"]>,
) {
  const base = buildDummyAnalysis("OpenAI").meta;
  return {
    ...base,
    ...overrides,
    sections: { ...base.sections, ...overrides.sections },
  };
}

describe("POST /api/analyze", () => {
  const originalEnv = process.env.PYTHON_ANALYSIS_API_URL;
  const originalFetch = global.fetch;

  beforeEach(() => {
    vi.spyOn(console, "warn").mockImplementation(() => {});
  });

  afterEach(() => {
    if (originalEnv === undefined) delete process.env.PYTHON_ANALYSIS_API_URL;
    else process.env.PYTHON_ANALYSIS_API_URL = originalEnv;
    global.fetch = originalFetch;
    vi.restoreAllMocks();
  });

  it("returns 400 when brandName is missing", async () => {
    delete process.env.PYTHON_ANALYSIS_API_URL;

    const response = await POST(makeRequest({}));

    expect(response.status).toBe(400);
    expect(await response.json()).toEqual({ error: "brandName is required" });
  });

  it("falls back to dummy data when PYTHON_ANALYSIS_API_URL is unset", async () => {
    delete process.env.PYTHON_ANALYSIS_API_URL;

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
    expect(data.meta.sections.cooccurrenceRanking).toBe("mock");
  });

  it("passes through the Python API response when it is valid", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: { cooccurrenceRanking: "real" },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("user_provided");
    expect(data.meta.sections.cooccurrenceRanking).toBe("real");
  });

  it("passes through an unavailable cooccurrenceRanking from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({
        documentsSource: "web_fetch",
        sections: { cooccurrenceRanking: "unavailable" },
        urlFetchResults: [
          { url: "http://localhost/x", success: false, error: "resolves to a disallowed address: 127.0.0.1" },
        ],
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", urls: ["http://localhost/x"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.sections.cooccurrenceRanking).toBe("unavailable");
    expect(data.meta.urlFetchResults).toHaveLength(1);
    expect(data.meta.urlFetchResults[0].success).toBe(false);
  });

  it("forwards documents to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(
      makeRequest({ brandName: "OpenAI", documents: ["文章1", "文章2"] }),
    );

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.documents).toEqual(["文章1", "文章2"]);
    expect(forwardedBody.urls).toBeUndefined();
  });

  it("forwards urls to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(
      makeRequest({
        brandName: "OpenAI",
        urls: ["https://example.com/a", "https://example.com/b"],
      }),
    );

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.urls).toEqual([
      "https://example.com/a",
      "https://example.com/b",
    ]);
    expect(forwardedBody.documents).toBeUndefined();
  });

  it("omits documents and urls from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.documents).toBeUndefined();
    expect(forwardedBody.urls).toBeUndefined();
  });

  it("falls back to dummy data when the Python API response fails schema validation", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ unexpected: "shape" }), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("failed schema validation"),
    );
  });

  it("falls back to dummy data when the Python API is unreachable", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("connection refused"));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
  });

  it("falls back to dummy data and logs a timeout-specific reason when the Python API times out", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    // Simulates what our own AbortController produces once
    // PYTHON_API_TIMEOUT_MS elapses, without actually waiting.
    const abortError = new DOMException("The operation was aborted.", "AbortError");
    global.fetch = vi.fn().mockRejectedValue(abortError);

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("timed out"),
    );
  });

  it("falls back to dummy data when the Python API returns a non-2xx status other than 400", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
  });

  it("forwards a 400 from the Python API as-is instead of falling back to dummy data", async () => {
    // Regression test: a 400 from Python means *our request* was
    // invalid (e.g. urls: [], too many documents) — the caller needs
    // to see that, not a silently-successful dummy response.
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "urls must not be empty" }), {
        status: 400,
      }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", urls: [] }),
    );
    const data = await response.json();

    expect(response.status).toBe(400);
    expect(data).toEqual({ error: "urls must not be empty" });
  });

  it("forwards a generic message when the Python API's 400 body is unexpected", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response("not json", { status: 400 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(400);
    expect(data).toEqual({ error: "invalid request" });
  });
});
