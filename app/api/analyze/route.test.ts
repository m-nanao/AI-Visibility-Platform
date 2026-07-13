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
    expect(data.meta.source).toBe("nextjs_mock");
    expect(data.meta.isMock).toBe(true);
  });

  it("passes through the Python API response when it is valid", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        source: "python_mock" as const,
        isMock: true,
        generatedAt: "2026-07-10T00:00:00.000Z",
      },
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.source).toBe("python_mock");
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
  });

  it("omits documents from the Python API request when not provided", async () => {
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
  });

  it("falls back to dummy data when the Python API response fails schema validation", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ unexpected: "shape" }), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.source).toBe("nextjs_mock");
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
    expect(data.meta.source).toBe("nextjs_mock");
  });

  it("falls back to dummy data when the Python API returns a non-2xx status", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.source).toBe("nextjs_mock");
  });
});
