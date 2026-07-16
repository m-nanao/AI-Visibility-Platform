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

  it("passes through meta.documentCount and meta.sourceTypes from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: { cooccurrenceRanking: "real" },
        documentCount: 2,
        sourceTypes: ["user_provided"],
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", documents: ["文章1", "文章2"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentCount).toBe(2);
    expect(data.meta.sourceTypes).toEqual(["user_provided"]);
  });

  it("passes through meta.chunkCount from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: { cooccurrenceRanking: "real" },
        documentCount: 1,
        sourceTypes: ["user_provided"],
        chunkCount: 3,
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", documents: ["長い文章"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.chunkCount).toBe(3);
  });

  it("passes through a real contextAnalysis from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      contextAnalysis: [
        {
          context: "料金・価格",
          description: "「OpenAI」に関連する文脈のうち、料金・価格に関する言及が1件見つかりました。",
          sentiment: "neutral",
          exampleQuote: "OpenAIの料金プランについて教えてください。",
        },
      ],
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: { cooccurrenceRanking: "real", contextAnalysis: "real" },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", documents: ["OpenAIの料金プランについて教えてください。"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.sections.contextAnalysis).toBe("real");
    expect(data.contextAnalysis).toEqual([
      {
        context: "料金・価格",
        description: "「OpenAI」に関連する文脈のうち、料金・価格に関する言及が1件見つかりました。",
        sentiment: "neutral",
        exampleQuote: "OpenAIの料金プランについて教えてください。",
      },
    ]);
  });

  it("passes through a real brand summary from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      summary: {
        brandName: "OpenAI",
        visibilityScore: 24,
        totalMentions: 2,
        sentimentBreakdown: { positive: 0, neutral: 100, negative: 0 },
        topPlatforms: ["入力テキスト"],
        summaryText: "OpenAIは取得した文章内で2回言及され、主に料金・価格の文脈で語られています。",
      },
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: { summary: "real", cooccurrenceRanking: "real", contextAnalysis: "real" },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", documents: ["OpenAIの料金プランについて教えてください。"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.sections.summary).toBe("real");
    expect(data.summary).toEqual({
      brandName: "OpenAI",
      visibilityScore: 24,
      totalMentions: 2,
      sentimentBreakdown: { positive: 0, neutral: 100, negative: 0 },
      topPlatforms: ["入力テキスト"],
      summaryText: "OpenAIは取得した文章内で2回言及され、主に料金・価格の文脈で語られています。",
    });
  });

  it("passes through real improvement suggestions from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      improvements: [
        {
          title: "導入事例・活用シーンの追加",
          description:
            "現在の文脈分析では導入事例・活用シーンに関する言及が確認できないため、具体的な導入事例やユースケースの追加を推奨します。",
          priority: "medium",
        },
      ],
      meta: pythonMetaOverride({
        documentsSource: "user_provided",
        sections: {
          summary: "real",
          cooccurrenceRanking: "real",
          contextAnalysis: "real",
          improvements: "real",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", documents: ["OpenAIの料金プランについて教えてください。"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.sections.improvements).toBe("real");
    expect(data.improvements).toEqual([
      {
        title: "導入事例・活用シーンの追加",
        description:
          "現在の文脈分析では導入事例・活用シーンに関する言及が確認できないため、具体的な導入事例やユースケースの追加を推奨します。",
        priority: "medium",
      },
    ]);
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

  it("forwards a valid aiOverviewMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", aiOverviewMode: "off" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.aiOverviewMode).toBe("off");
  });

  it("drops an invalid aiOverviewMode instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", aiOverviewMode: "real" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.aiOverviewMode).toBeUndefined();
  });

  it("omits aiOverviewMode from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.aiOverviewMode).toBeUndefined();
  });

  it("accepts an unavailable aiOverviewComparison with aiOverviewProvider metadata from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "unavailable" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "unavailable",
          reason: "DataForSEO provider is not yet implemented; no external API call was made.",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.sections.aiOverviewComparison).toBe("unavailable");
    expect(data.aiOverviewComparison).toEqual([]);
    expect(data.meta.aiOverviewProvider).toEqual({
      mode: "dataforseo",
      status: "unavailable",
      reason: "DataForSEO provider is not yet implemented; no external API call was made.",
    });
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

  it("forwards a generic safe message when the Python API's 400 body is unexpected", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response("not json", { status: 400 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(400);
    expect(data).toEqual({ error: "入力内容を確認してください" });
  });

  it("treats a 422 from the Python API the same as a 400 (own {error} shape forwarded)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "brandName is required" }), {
        status: 422,
      }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(400);
    expect(data).toEqual({ error: "brandName is required" });
  });

  it("never exposes FastAPI's raw detail array from a 422 response", async () => {
    // Regression guard: FastAPI's default RequestValidationError shape
    // is { detail: [{ loc, msg, type }, ...] } — this must never reach
    // the user as-is.
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          detail: [
            { loc: ["body", "urls", 0], msg: "value is not a valid string", type: "type_error.str" },
          ],
        }),
        { status: 422 },
      ),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(400);
    expect(data).toEqual({ error: "入力内容を確認してください" });
    expect(JSON.stringify(data)).not.toContain("type_error");
  });
});
