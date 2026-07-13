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

  it("falls back to dummy data when the Python API returns a non-2xx status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
  });
});
