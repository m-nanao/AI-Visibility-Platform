import {
  afterEach,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";

const getServerSupabaseAccessTokenMock = vi.fn<() => Promise<string | null>>();

vi.mock("../../lib/supabase/server", () => ({
  getServerSupabaseAccessToken: () => getServerSupabaseAccessTokenMock(),
}));

import { POST } from "./route";
import { buildDummyAnalysis } from "../../lib/dummy-data";
import {
  ANALYZE_ACCESS_DENIED_MESSAGE,
  ANALYZE_AUTH_CONFIG_ERROR_MESSAGE,
  ANALYZE_AUTH_REQUIRED_MESSAGE,
  ANALYZE_FALLBACK_HEADER,
  ANALYZE_FALLBACK_REASON_HEADER,
} from "../../lib/analysis-request";

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
    getServerSupabaseAccessTokenMock.mockReset().mockResolvedValue(null);
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
    expect(response.headers.get(ANALYZE_FALLBACK_HEADER)).toBe("1");
    expect(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)).toBe("not_configured");
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
    // A real response must never carry the fallback headers — the
    // caller (app/page.tsx) relies on their *absence* to know this is
    // a genuine result, not dummy data.
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
    expect(response.headers.has(ANALYZE_FALLBACK_REASON_HEADER)).toBe(false);
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

  it("forwards the explicit dataforseo_sandbox aiOverviewMode to the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo_sandbox" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.aiOverviewMode).toBe("dataforseo_sandbox");
  });

  it("forwards the explicit dataforseo_live aiOverviewMode to the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo_live" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.aiOverviewMode).toBe("dataforseo_live");
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

  it("forwards a valid chatgptMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", chatgptMode: "openai" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.chatgptMode).toBe("openai");
  });

  it("drops an invalid chatgptMode instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", chatgptMode: "chatgpt" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.chatgptMode).toBeUndefined();
  });

  it("omits chatgptMode from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.chatgptMode).toBeUndefined();
  });

  it("forwards a valid claudeMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", claudeMode: "anthropic" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBe("anthropic");
  });

  it("forwards an explicit off claudeMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", claudeMode: "off" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBe("off");
  });

  it("drops an invalid claudeMode instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", claudeMode: "claude" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBeUndefined();
  });

  it("omits claudeMode from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBeUndefined();
  });

  it("never forwards a claudeMode field that looks like an API key", async () => {
    // Defense-in-depth: even if a caller tried to smuggle a secret
    // through this field, CLAUDE_MODES.includes() only accepts the
    // literal "off"/"anthropic" strings, so anything else (including
    // an attempted API key value) is dropped rather than forwarded.
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", claudeMode: "sk-ant-not-a-real-key" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBeUndefined();
  });

  it("forwards a valid geminiMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", geminiMode: "google" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.geminiMode).toBe("google");
  });

  it("forwards an explicit off geminiMode to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", geminiMode: "off" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.geminiMode).toBe("off");
  });

  it("drops an invalid geminiMode instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", geminiMode: "gemini" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.geminiMode).toBeUndefined();
  });

  it("omits geminiMode from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.geminiMode).toBeUndefined();
  });

  it("never forwards a geminiMode field that looks like an API key", async () => {
    // Defense-in-depth: even if a caller tried to smuggle a secret
    // through this field, GEMINI_MODES.includes() only accepts the
    // literal "off"/"google" strings, so anything else (including an
    // attempted API key value) is dropped rather than forwarded.
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", geminiMode: "AIzaSyNotARealKey1234567890" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.geminiMode).toBeUndefined();
  });

  it("forwards claudeMode and geminiMode together without interfering with each other", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", claudeMode: "anthropic", geminiMode: "google" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.claudeMode).toBe("anthropic");
    expect(forwardedBody.geminiMode).toBe("google");
  });

  it("forwards a valid commonCrawlMode and commonCrawlDomain to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("Cybozu");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(
      makeRequest({
        brandName: "Cybozu",
        commonCrawlMode: "domain",
        commonCrawlDomain: "cybozu.co.jp",
      }),
    );

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.commonCrawlMode).toBe("domain");
    expect(forwardedBody.commonCrawlDomain).toBe("cybozu.co.jp");
  });

  it("drops an invalid commonCrawlMode instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("Cybozu");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "Cybozu", commonCrawlMode: "brand_name" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.commonCrawlMode).toBeUndefined();
  });

  it("drops a non-string commonCrawlDomain instead of forwarding it", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("Cybozu");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(
      makeRequest({ brandName: "Cybozu", commonCrawlMode: "domain", commonCrawlDomain: 123 }),
    );

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.commonCrawlDomain).toBeUndefined();
  });

  it("omits commonCrawlMode/commonCrawlDomain from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = buildDummyAnalysis("OpenAI");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const forwardedBody = JSON.parse(requestInit.body as string);
    expect(forwardedBody.commonCrawlMode).toBeUndefined();
    expect(forwardedBody.commonCrawlDomain).toBeUndefined();
  });

  it("passes through meta.commonCrawlProvider and an extra Document source from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("Cybozu"),
      meta: pythonMetaOverride({
        sourceTypes: ["development_sample", "common_crawl"],
        commonCrawlProvider: {
          mode: "domain",
          status: "real",
          reason: "Common Crawl added 1 document(s) for cybozu.co.jp.",
          domain: "cybozu.co.jp",
          crawlIndex: "CC-MAIN-2026-08",
          candidateCount: 1,
          documentCount: 1,
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "Cybozu", commonCrawlMode: "domain", commonCrawlDomain: "cybozu.co.jp" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.commonCrawlProvider).toEqual({
      mode: "domain",
      status: "real",
      reason: "Common Crawl added 1 document(s) for cybozu.co.jp.",
      domain: "cybozu.co.jp",
      crawlIndex: "CC-MAIN-2026-08",
      candidateCount: 1,
      documentCount: 1,
    });
    expect(data.meta.sourceTypes).toContain("common_crawl");
  });

  it("accepts a response without meta.commonCrawlProvider (existing/older backend shape)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({}),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.commonCrawlProvider).toBeUndefined();
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

  it("passes through aiOverviewProvider.environment (sandbox/live) from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Google AI Mode (DataForSEO Live)", mentioned: true, rank: 1, summary: "OpenAI is..." },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Live AI Mode request succeeded.",
          environment: "live",
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
    expect(data.meta.aiOverviewProvider.environment).toBe("live");
  });

  it("accepts the explicit dataforseo_sandbox/dataforseo_live aiOverviewProvider.mode values from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Google AI Mode (DataForSEO Live)", mentioned: true, rank: 1, summary: "OpenAI is..." },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo_live",
          status: "real",
          reason: "DataForSEO Live AI Mode request succeeded.",
          environment: "live",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo_live" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.aiOverviewProvider.mode).toBe("dataforseo_live");
    expect(data.meta.aiOverviewProvider.environment).toBe("live");
  });

  it("passes through meta.chatgptProvider and an extra ChatGPT card from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Google AI Mode (DataForSEO Sandbox)", mentioned: true, rank: 1, summary: "OpenAI is..." },
        { platform: "ChatGPT (OpenAI API)", mentioned: true, rank: null, summary: "OpenAI is a well-known AI lab." },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Sandbox AI Mode request succeeded.",
          environment: "sandbox",
        },
        chatgptProvider: {
          mode: "openai",
          status: "real",
          reason: "ChatGPT OpenAI API request succeeded.",
          environment: "api",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo", chatgptMode: "openai" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.chatgptProvider).toEqual({
      mode: "openai",
      status: "real",
      reason: "ChatGPT OpenAI API request succeeded.",
      environment: "api",
    });
    const platforms = data.aiOverviewComparison.map((item: { platform: string }) => item.platform);
    expect(platforms).toContain("ChatGPT (OpenAI API)");
  });

  it("accepts a response without meta.chatgptProvider (existing/older backend shape)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({}),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.chatgptProvider).toBeUndefined();
  });

  it("passes through meta.claudeProvider and an extra Claude card from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Google AI Mode (DataForSEO Sandbox)", mentioned: true, rank: 1, summary: "OpenAI is..." },
        { platform: "Claude (Anthropic API)", mentioned: true, rank: null, summary: "OpenAI is a well-known AI lab." },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Sandbox AI Mode request succeeded.",
          environment: "sandbox",
        },
        claudeProvider: {
          mode: "anthropic",
          status: "real",
          reason: "Claude Anthropic API request succeeded.",
          environment: "api",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo", claudeMode: "anthropic" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.claudeProvider).toEqual({
      mode: "anthropic",
      status: "real",
      reason: "Claude Anthropic API request succeeded.",
      environment: "api",
    });
    const platforms = data.aiOverviewComparison.map((item: { platform: string }) => item.platform);
    expect(platforms).toContain("Claude (Anthropic API)");

    // API key must never appear in the response body forwarded to the browser.
    const body = JSON.stringify(data);
    expect(body).not.toMatch(/sk-ant-/);
  });

  it("accepts a response without meta.claudeProvider (existing/older backend shape)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({}),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.claudeProvider).toBeUndefined();
  });

  it("passes through meta.geminiProvider and an extra Gemini card from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Google AI Mode (DataForSEO Sandbox)", mentioned: true, rank: 1, summary: "OpenAI is..." },
        { platform: "Gemini (Google API)", mentioned: true, rank: null, summary: "OpenAI is a well-known AI lab." },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Sandbox AI Mode request succeeded.",
          environment: "sandbox",
        },
        geminiProvider: {
          mode: "google",
          status: "real",
          reason: "Gemini Google API request succeeded.",
          environment: "api",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", aiOverviewMode: "dataforseo", geminiMode: "google" }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.geminiProvider).toEqual({
      mode: "google",
      status: "real",
      reason: "Gemini Google API request succeeded.",
      environment: "api",
    });
    const platforms = data.aiOverviewComparison.map((item: { platform: string }) => item.platform);
    expect(platforms).toContain("Gemini (Google API)");

    // API key must never appear in the response body forwarded to the browser.
    const body = JSON.stringify(data);
    expect(body).not.toMatch(/AIzaSy/);
  });

  it("accepts a response without meta.geminiProvider (existing/older backend shape)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({}),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.geminiProvider).toBeUndefined();
  });

  it("passes through aiOverviewComparison's fullSummary/references/ownDomainReferenced from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Google AI Mode (DataForSEO Sandbox)",
          mentioned: true,
          rank: 1,
          summary: "OpenAI is a well-known AI lab.",
          fullSummary: "OpenAI is a well-known AI lab that builds ChatGPT and other AI products.",
          references: [
            { title: "About OpenAI", domain: "openai.com", url: "https://openai.com/about" },
          ],
          ownDomainReferenced: true,
        },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Sandbox AI Mode request succeeded.",
          environment: "sandbox",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", urls: ["https://openai.com/pricing"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    const item = data.aiOverviewComparison[0];
    expect(item.fullSummary).toBe(
      "OpenAI is a well-known AI lab that builds ChatGPT and other AI products.",
    );
    expect(item.references).toEqual([
      { title: "About OpenAI", domain: "openai.com", url: "https://openai.com/about" },
    ]);
    expect(item.ownDomainReferenced).toBe(true);
  });

  it("passes through aiOverviewComparison's reference category/referenceSummary from the Python API", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Google AI Mode (DataForSEO Sandbox)",
          mentioned: true,
          rank: 1,
          summary: "OpenAI is a well-known AI lab.",
          references: [
            { title: "About OpenAI", domain: "openai.com", url: "https://openai.com/about", category: "official" },
            { domain: "ja.wikipedia.org", category: "wikipedia" },
          ],
          referenceSummary: {
            total: 2,
            official: 1,
            thirdParty: 1,
            categories: { official: 1, wikipedia: 1 },
          },
          ownDomainReferenced: true,
        },
      ],
      meta: pythonMetaOverride({
        sections: { aiOverviewComparison: "real" },
        aiOverviewProvider: {
          mode: "dataforseo",
          status: "real",
          reason: "DataForSEO Sandbox AI Mode request succeeded.",
          environment: "sandbox",
        },
      }),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(
      makeRequest({ brandName: "OpenAI", urls: ["https://openai.com/pricing"] }),
    );
    const data = await response.json();

    expect(response.status).toBe(200);
    const item = data.aiOverviewComparison[0];
    expect(item.references[0].category).toBe("official");
    expect(item.references[1].category).toBe("wikipedia");
    expect(item.referenceSummary).toEqual({
      total: 2,
      official: 1,
      thirdParty: 1,
      categories: { official: 1, wikipedia: 1 },
    });
  });

  it("accepts an aiOverviewComparison item without fullSummary/references/ownDomainReferenced (existing mock shape)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      meta: pythonMetaOverride({}),
    };
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(pythonResult), { status: 200 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.aiOverviewComparison.length).toBeGreaterThan(0);
    for (const item of data.aiOverviewComparison) {
      expect(item.fullSummary).toBeUndefined();
      expect(item.references).toBeUndefined();
      expect(item.referenceSummary).toBeUndefined();
      expect(item.ownDomainReferenced).toBeUndefined();
    }
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
    expect(response.headers.get(ANALYZE_FALLBACK_HEADER)).toBe("1");
    expect(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)).toBe("schema_mismatch");
  });

  it("falls back to dummy data when the Python API is unreachable", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockRejectedValue(new Error("connection refused"));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
    expect(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)).toBe("request_failed");
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
    expect(response.headers.get(ANALYZE_FALLBACK_HEADER)).toBe("1");
    expect(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)).toBe("timeout");
  });

  it("falls back to dummy data when the Python API returns a non-2xx status other than 400", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(new Response("", { status: 500 }));

    const response = await POST(makeRequest({ brandName: "OpenAI" }));
    const data = await response.json();

    expect(response.status).toBe(200);
    expect(data.meta.documentsSource).toBe("development_sample");
    expect(response.headers.get(ANALYZE_FALLBACK_REASON_HEADER)).toBe("upstream_error");
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

  // --- Immediate-display / history-detail schema parity
  // (fix/analyze-immediate-result-and-web-ai-gap-quality) — a real
  // Python API response carrying every recently-added optional field
  // (webAiGap, finishReason/isTruncated/note) must pass through this
  // route exactly like the already-covered claudeProvider/
  // geminiProvider/commonCrawlProvider cases above, never silently
  // falling back to dummy data for a shape that
  // app/lib/analysis-history.ts's resolveHistoryDetailFetchOutcome()
  // (used for the exact same stored JSON on /history/[id]) already
  // accepts via the same parseAnalysisResult(). ---

  it("passes through a real webAiGap (with truncation fields on an aiOverviewComparison item) from the Python API instead of falling back to dummy data", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const pythonResult = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Gemini (Google API)",
          mentioned: true,
          rank: null,
          summary: "OpenAI is an AI research company.",
          finishReason: "MAX_TOKENS",
          isTruncated: true,
          note: "Gemini APIの出力が途中で終了した可能性があります。",
        },
      ],
      webAiGap: {
        status: "real",
        webContext: {
          summary: "OpenAIは契約期間の縛りなし・初期費用0円で利用できます。",
          sourceType: "web_fetch",
        },
        aiContexts: [
          { platform: "gemini", summary: "OpenAIはAI研究を行う会社です。", status: "real" },
        ],
        gapSummary: "Web上では料金・契約条件に関する説明が目立つ一方、AI回答ではサービス内容の説明が中心です。",
        suggestions: ["社名の近くに主要サービス名を明記する"],
        note: "Web上の情報環境とAI回答の単発観測を比較した補助的な見立てです。AIの内部認識を直接示すものではありません。",
      },
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
    // Real data must come through as-is — the surest sign a fallback
    // did NOT happen is documentsSource staying "user_provided" rather
    // than reverting to "development_sample", plus the absence of the
    // fallback headers.
    expect(data.meta.documentsSource).toBe("user_provided");
    expect(data.webAiGap.status).toBe("real");
    expect(data.webAiGap.gapSummary).toContain("料金・契約条件");
    expect(data.aiOverviewComparison[0].isTruncated).toBe(true);
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
  });

  // --- Task 6-B2 (feature/sync-analyze-jwt-project-auth): JWT/projectId
  // forwarding and auth-error handling. ANALYZE_AUTH_REQUIRED itself is
  // a Python-API-side flag this route has no knowledge of — these
  // tests only verify that (a) a JWT/projectId are forwarded whenever
  // present, regardless of this app's own state, and (b) a 401/403/
  // auth-config 503 from the Python API is surfaced as a real error
  // rather than ever becoming a dummy-data "success".

  it("forwards the caller's Supabase access token as Authorization: Bearer when present", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    getServerSupabaseAccessTokenMock.mockResolvedValue("user-access-token");
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildDummyAnalysis("OpenAI")), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.get("Authorization")).toBe("Bearer user-access-token");
  });

  it("sends no Authorization header when there is no session", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildDummyAnalysis("OpenAI")), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const headers = new Headers(requestInit.headers as HeadersInit);
    expect(headers.has("Authorization")).toBe(false);
  });

  it("forwards a valid projectId to the Python API when provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildDummyAnalysis("OpenAI")), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI", projectId: "project-123" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const sentBody = JSON.parse(requestInit.body as string);
    expect(sentBody.projectId).toBe("project-123");
  });

  it("omits projectId from the Python API request when not provided", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(buildDummyAnalysis("OpenAI")), { status: 200 }),
    );
    global.fetch = fetchMock;

    await POST(makeRequest({ brandName: "OpenAI" }));

    const [, requestInit] = fetchMock.mock.calls[0];
    const sentBody = JSON.parse(requestInit.body as string);
    expect(sentBody).not.toHaveProperty("projectId");
  });

  it("returns 401 (never a dummy-data fallback) when the Python API rejects with 401", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "authentication required" }), { status: 401 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI", projectId: "p1" }));
    const body = await response.json();

    expect(response.status).toBe(401);
    expect(body).toEqual({ error: ANALYZE_AUTH_REQUIRED_MESSAGE });
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
  });

  it("returns 403 (never a dummy-data fallback) when the Python API rejects with 403", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "access denied to the specified project" }),
        { status: 403 },
      ),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI", projectId: "not-mine" }));
    const body = await response.json();

    expect(response.status).toBe(403);
    expect(body).toEqual({ error: ANALYZE_ACCESS_DENIED_MESSAGE });
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
  });

  it("returns 503 (never a dummy-data fallback) when the Python API's 503 means JWT verification is misconfigured", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "analyze JWT verification is not configured" }),
        { status: 503 },
      ),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI", projectId: "p1" }));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: ANALYZE_AUTH_CONFIG_ERROR_MESSAGE });
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
  });

  it("returns 503 (never a dummy-data fallback) when the Python API's 503 means the project-access check itself failed", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: "failed to verify project access" }), { status: 503 }),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI", projectId: "p1" }));
    const body = await response.json();

    expect(response.status).toBe(503);
    expect(body).toEqual({ error: ANALYZE_AUTH_CONFIG_ERROR_MESSAGE });
    expect(response.headers.has(ANALYZE_FALLBACK_HEADER)).toBe(false);
  });

  it("still falls back to dummy data for an unrelated 503 (Python API not configured/DB unreachable)", async () => {
    process.env.PYTHON_ANALYSIS_API_URL = "http://python-api.test";
    global.fetch = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ error: "analysis history read API is not configured" }),
        { status: 503 },
      ),
    );

    const response = await POST(makeRequest({ brandName: "OpenAI" }));

    expect(response.status).toBe(200);
    expect(response.headers.get(ANALYZE_FALLBACK_HEADER)).toBe("1");
  });
});
