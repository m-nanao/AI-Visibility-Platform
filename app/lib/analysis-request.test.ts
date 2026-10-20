import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ANALYZE_CONFLICT_GENERIC_MESSAGE,
  ANALYZE_PREVIOUSLY_FAILED_CODE,
  ANALYZE_REQUEST_CANCELLED_CODE,
  ANALYZE_REQUEST_CONFLICT_CODE,
  ANALYZE_STILL_RUNNING_CODE,
  buildAnalyzeRequestBody,
  clearPendingSyncAnalysisRequest,
  getAnalyzeConflictMessage,
  getAnalyzeFallbackMessage,
  isAiOverviewModeSelectorEnabled,
  isAnalyzeAuthRequiredEnabled,
  isChatGptModeSelectorEnabled,
  isClaudeModeSelectorEnabled,
  isCommonCrawlModeSelectorEnabled,
  isGeminiModeSelectorEnabled,
  isTerminalAnalyzeConflictCode,
  resolveRequestIdForSyncAnalysis,
} from "./analysis-request";

describe("isAiOverviewModeSelectorEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR = "false";
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR = "TRUE";
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR = "true";
    expect(isAiOverviewModeSelectorEnabled()).toBe(true);
  });
});

describe("isAnalyzeAuthRequiredEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED;
    } else {
      process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED;
    expect(isAnalyzeAuthRequiredEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED = "false";
    expect(isAnalyzeAuthRequiredEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED = "TRUE";
    expect(isAnalyzeAuthRequiredEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ANALYZE_AUTH_REQUIRED = "true";
    expect(isAnalyzeAuthRequiredEnabled()).toBe(true);
  });
});

describe("isChatGptModeSelectorEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;
    expect(isChatGptModeSelectorEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR = "false";
    expect(isChatGptModeSelectorEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR = "TRUE";
    expect(isChatGptModeSelectorEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR = "true";
    expect(isChatGptModeSelectorEnabled()).toBe(true);
  });

  it("is independent from the AI Overview mode selector's own flag", () => {
    process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR = "true";
    delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    expect(isChatGptModeSelectorEnabled()).toBe(true);
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
  });
});

describe("isCommonCrawlModeSelectorEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR;
    expect(isCommonCrawlModeSelectorEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR = "false";
    expect(isCommonCrawlModeSelectorEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR = "TRUE";
    expect(isCommonCrawlModeSelectorEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR = "true";
    expect(isCommonCrawlModeSelectorEnabled()).toBe(true);
  });

  it("is independent from the AI Overview/ChatGPT mode selectors' own flags", () => {
    process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR = "true";
    delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;
    expect(isCommonCrawlModeSelectorEnabled()).toBe(true);
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
    expect(isChatGptModeSelectorEnabled()).toBe(false);
  });
});

describe("isClaudeModeSelectorEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR;
    expect(isClaudeModeSelectorEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR = "false";
    expect(isClaudeModeSelectorEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR = "TRUE";
    expect(isClaudeModeSelectorEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR = "true";
    expect(isClaudeModeSelectorEnabled()).toBe(true);
  });

  it("is independent from the other mode selectors' own flags", () => {
    process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR = "true";
    delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR;
    expect(isClaudeModeSelectorEnabled()).toBe(true);
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
    expect(isChatGptModeSelectorEnabled()).toBe(false);
    expect(isCommonCrawlModeSelectorEnabled()).toBe(false);
    expect(isGeminiModeSelectorEnabled()).toBe(false);
  });
});

describe("isGeminiModeSelectorEnabled", () => {
  const originalValue = process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR;

  afterEach(() => {
    if (originalValue === undefined) {
      delete process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR;
    } else {
      process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR = originalValue;
    }
  });

  it("is disabled when the env var is unset", () => {
    delete process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR;
    expect(isGeminiModeSelectorEnabled()).toBe(false);
  });

  it("is disabled when the env var is \"false\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR = "false";
    expect(isGeminiModeSelectorEnabled()).toBe(false);
  });

  it("is disabled for any value other than the exact string \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR = "TRUE";
    expect(isGeminiModeSelectorEnabled()).toBe(false);
  });

  it("is enabled only when the env var is exactly \"true\"", () => {
    process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR = "true";
    expect(isGeminiModeSelectorEnabled()).toBe(true);
  });

  it("is independent from the other mode selectors' own flags, including Claude's", () => {
    process.env.NEXT_PUBLIC_ENABLE_GEMINI_MODE_SELECTOR = "true";
    delete process.env.NEXT_PUBLIC_ENABLE_AI_OVERVIEW_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_CHATGPT_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_COMMON_CRAWL_MODE_SELECTOR;
    delete process.env.NEXT_PUBLIC_ENABLE_CLAUDE_MODE_SELECTOR;
    expect(isGeminiModeSelectorEnabled()).toBe(true);
    expect(isAiOverviewModeSelectorEnabled()).toBe(false);
    expect(isChatGptModeSelectorEnabled()).toBe(false);
    expect(isCommonCrawlModeSelectorEnabled()).toBe(false);
    expect(isClaudeModeSelectorEnabled()).toBe(false);
  });
});

describe("buildAnalyzeRequestBody", () => {
  it("includes only brandName when there are no urls and no aiOverviewMode (existing/default behavior)", () => {
    expect(buildAnalyzeRequestBody("Acme", [])).toEqual({ brandName: "Acme" });
  });

  it("includes urls only when non-empty", () => {
    expect(buildAnalyzeRequestBody("Acme", ["https://acme.example.com"])).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
    });
  });

  it("omits aiOverviewMode when not passed (mode selector not shown)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.aiOverviewMode).toBeUndefined();
    expect("aiOverviewMode" in body).toBe(false);
  });

  it("includes aiOverviewMode when passed (mode selector shown and a value selected)", () => {
    expect(buildAnalyzeRequestBody("Acme", [], "dataforseo")).toEqual({
      brandName: "Acme",
      aiOverviewMode: "dataforseo",
    });
  });

  it("includes mock/off/dataforseo aiOverviewMode values", () => {
    expect(buildAnalyzeRequestBody("Acme", [], "mock").aiOverviewMode).toBe("mock");
    expect(buildAnalyzeRequestBody("Acme", [], "off").aiOverviewMode).toBe("off");
    expect(buildAnalyzeRequestBody("Acme", [], "dataforseo").aiOverviewMode).toBe("dataforseo");
  });

  it("includes the explicit dataforseo_sandbox aiOverviewMode value", () => {
    expect(buildAnalyzeRequestBody("Acme", [], "dataforseo_sandbox")).toEqual({
      brandName: "Acme",
      aiOverviewMode: "dataforseo_sandbox",
    });
  });

  it("includes the explicit dataforseo_live aiOverviewMode value", () => {
    expect(buildAnalyzeRequestBody("Acme", [], "dataforseo_live")).toEqual({
      brandName: "Acme",
      aiOverviewMode: "dataforseo_live",
    });
  });

  it("includes both urls and aiOverviewMode together", () => {
    expect(
      buildAnalyzeRequestBody("Acme", ["https://acme.example.com"], "dataforseo"),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
    });
  });

  it("omits chatgptMode when not passed (mode selector not shown)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.chatgptMode).toBeUndefined();
    expect("chatgptMode" in body).toBe(false);
  });

  it("includes chatgptMode when passed (mode selector shown and a value selected)", () => {
    expect(buildAnalyzeRequestBody("Acme", [], undefined, "openai")).toEqual({
      brandName: "Acme",
      chatgptMode: "openai",
    });
  });

  it("includes off/openai chatgptMode values", () => {
    expect(buildAnalyzeRequestBody("Acme", [], undefined, "off").chatgptMode).toBe("off");
    expect(buildAnalyzeRequestBody("Acme", [], undefined, "openai").chatgptMode).toBe("openai");
  });

  it("includes urls, aiOverviewMode, and chatgptMode together", () => {
    expect(
      buildAnalyzeRequestBody("Acme", ["https://acme.example.com"], "dataforseo", "openai"),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
      chatgptMode: "openai",
    });
  });

  it("omits commonCrawlMode when not passed (selector not shown)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.commonCrawlMode).toBeUndefined();
    expect("commonCrawlMode" in body).toBe(false);
  });

  it("omits commonCrawlMode when explicitly \"off\" (same as omitting it)", () => {
    const body = buildAnalyzeRequestBody("Acme", [], undefined, undefined, "off");
    expect("commonCrawlMode" in body).toBe(false);
  });

  it("includes commonCrawlMode when \"domain\" is selected", () => {
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, "domain"),
    ).toEqual({
      brandName: "Acme",
      commonCrawlMode: "domain",
    });
  });

  it("omits commonCrawlDomain when not passed", () => {
    const body = buildAnalyzeRequestBody("Acme", [], undefined, undefined, "domain");
    expect(body.commonCrawlDomain).toBeUndefined();
  });

  it("includes commonCrawlDomain when a non-empty value is passed", () => {
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, "domain", "cybozu.co.jp"),
    ).toEqual({
      brandName: "Acme",
      commonCrawlMode: "domain",
      commonCrawlDomain: "cybozu.co.jp",
    });
  });

  it("trims commonCrawlDomain before including it", () => {
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, "domain", "  cybozu.co.jp  "),
    ).toMatchObject({ commonCrawlDomain: "cybozu.co.jp" });
  });

  it("omits commonCrawlDomain when it is empty/whitespace-only", () => {
    const body = buildAnalyzeRequestBody("Acme", [], undefined, undefined, "domain", "   ");
    expect(body.commonCrawlDomain).toBeUndefined();
    expect("commonCrawlDomain" in body).toBe(false);
  });

  it("includes urls, aiOverviewMode, chatgptMode, commonCrawlMode, and commonCrawlDomain together", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        ["https://acme.example.com"],
        "dataforseo",
        "openai",
        "domain",
        "acme.example.com",
      ),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
      chatgptMode: "openai",
      commonCrawlMode: "domain",
      commonCrawlDomain: "acme.example.com",
    });
  });

  it("omits claudeMode when not passed (selector not shown)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.claudeMode).toBeUndefined();
    expect("claudeMode" in body).toBe(false);
  });

  it("includes claudeMode when passed (mode selector shown and a value selected)", () => {
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, undefined, undefined, "anthropic"),
    ).toEqual({
      brandName: "Acme",
      claudeMode: "anthropic",
    });
  });

  it("includes off/anthropic claudeMode values (default off is sent explicitly when the selector is shown)", () => {
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, undefined, undefined, "off")
        .claudeMode,
    ).toBe("off");
    expect(
      buildAnalyzeRequestBody("Acme", [], undefined, undefined, undefined, undefined, "anthropic")
        .claudeMode,
    ).toBe("anthropic");
  });

  it("includes urls, aiOverviewMode, chatgptMode, commonCrawlMode, commonCrawlDomain, and claudeMode together", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        ["https://acme.example.com"],
        "dataforseo",
        "openai",
        "domain",
        "acme.example.com",
        "anthropic",
      ),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
      chatgptMode: "openai",
      commonCrawlMode: "domain",
      commonCrawlDomain: "acme.example.com",
      claudeMode: "anthropic",
    });
  });

  it("omits geminiMode when not passed (selector not shown)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.geminiMode).toBeUndefined();
    expect("geminiMode" in body).toBe(false);
  });

  it("includes geminiMode when passed (mode selector shown and a value selected)", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "google",
      ),
    ).toEqual({
      brandName: "Acme",
      geminiMode: "google",
    });
  });

  it("includes off/google geminiMode values (default off is sent explicitly when the selector is shown)", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "off",
      ).geminiMode,
    ).toBe("off");
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "google",
      ).geminiMode,
    ).toBe("google");
  });

  it("does not affect claudeMode when geminiMode is also passed (both selectors can be shown independently)", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        "anthropic",
        "google",
      ),
    ).toEqual({
      brandName: "Acme",
      claudeMode: "anthropic",
      geminiMode: "google",
    });
  });

  it("includes urls, aiOverviewMode, chatgptMode, commonCrawlMode, commonCrawlDomain, claudeMode, and geminiMode together", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        ["https://acme.example.com"],
        "dataforseo",
        "openai",
        "domain",
        "acme.example.com",
        "anthropic",
        "google",
      ),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
      chatgptMode: "openai",
      commonCrawlMode: "domain",
      commonCrawlDomain: "acme.example.com",
      claudeMode: "anthropic",
      geminiMode: "google",
    });
  });

  // --- projectId (Task 6-B2, feature/sync-analyze-jwt-project-auth) ---

  it("omits projectId when not passed (analyzeAuthRequired disabled)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.projectId).toBeUndefined();
    expect("projectId" in body).toBe(false);
  });

  it("includes projectId when passed", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "project-123",
      ),
    ).toEqual({ brandName: "Acme", projectId: "project-123" });
  });

  it("trims projectId before including it", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "  project-123  ",
      ),
    ).toEqual({ brandName: "Acme", projectId: "project-123" });
  });

  it("omits a blank/whitespace-only projectId", () => {
    const body = buildAnalyzeRequestBody(
      "Acme",
      [],
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      "   ",
    );
    expect("projectId" in body).toBe(false);
  });

  // --- requestId (Task 6-B3, feature/sync-analyze-jwt-project-auth) ---

  it("omits requestId when not passed", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    expect(body.requestId).toBeUndefined();
    expect("requestId" in body).toBe(false);
  });

  it("includes requestId when passed", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "project-123",
        "req-1",
      ),
    ).toEqual({ brandName: "Acme", projectId: "project-123", requestId: "req-1" });
  });

  it("trims requestId before including it", () => {
    expect(
      buildAnalyzeRequestBody(
        "Acme",
        [],
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        undefined,
        "  req-1  ",
      ).requestId,
    ).toBe("req-1");
  });

  it("omits a blank/whitespace-only requestId", () => {
    const body = buildAnalyzeRequestBody(
      "Acme",
      [],
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      "   ",
    );
    expect("requestId" in body).toBe(false);
  });
});

// This project's vitest run doesn't use a jsdom environment (no
// `window` global by default) — see app/lib/analysis-jobs.test.ts's
// own makeFakeWindow() for the same pattern, mirrored here since
// resolveRequestIdForSyncAnalysis()/clearPendingSyncAnalysisRequest()
// use sessionStorage exactly the same way that file's
// resolveIdempotencyKeyForJobSubmission()/clearPendingJobSubmission()
// do.
function makeFakeWindow() {
  const store = new Map<string, string>();
  return {
    sessionStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    },
  };
}

describe("resolveRequestIdForSyncAnalysis / clearPendingSyncAnalysisRequest", () => {
  beforeEach(() => {
    vi.stubGlobal("window", makeFakeWindow());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("generates a new requestId for a first submission", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const id = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    expect(id).toBe("generated-1");
  });

  it("reuses the stored requestId for a retry of the exact same input by the same user/project", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const first = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    const second = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-2");
    expect(first).toBe("generated-1");
    expect(second).toBe("generated-1");
  });

  it("generates a fresh requestId when the input changes", () => {
    const first = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      buildAnalyzeRequestBody("Acme", []),
      () => "generated-1",
    );
    const second = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      buildAnalyzeRequestBody("OtherBrand", []),
      () => "generated-2",
    );
    expect(first).toBe("generated-1");
    expect(second).toBe("generated-2");
  });

  it("generates a fresh requestId for a different user even with identical input", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const first = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    const second = resolveRequestIdForSyncAnalysis("user-2", "project-1", body, () => "generated-2");
    expect(first).toBe("generated-1");
    expect(second).toBe("generated-2");
  });

  it("generates a fresh requestId for a different project even with identical input", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const first = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    const second = resolveRequestIdForSyncAnalysis("user-1", "project-2", body, () => "generated-2");
    expect(first).toBe("generated-1");
    expect(second).toBe("generated-2");
  });

  it("generates a fresh requestId again after clearPendingSyncAnalysisRequest()", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const first = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    clearPendingSyncAnalysisRequest();
    const second = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-2");
    expect(first).toBe("generated-1");
    expect(second).toBe("generated-2");
  });

  it("does not throw and still generates a requestId when there is no window", () => {
    vi.unstubAllGlobals();
    const body = buildAnalyzeRequestBody("Acme", []);
    const id = resolveRequestIdForSyncAnalysis("user-1", "project-1", body, () => "generated-1");
    expect(id).toBe("generated-1");
  });
});

// --- Task 6-B3 audit fix regression (不具合A): app/page.tsx's
// handleAnalyze() has no exported function of its own (this project
// has no React component test infrastructure — see
// app/lib/analysis-jobs.test.ts's own makeFakeWindow()-based
// convention for why logic lives in lib/ files instead), so these
// tests reproduce its exact post-fetch decision sequence verbatim
// against the real exported functions, proving the fixed behavior:
// a dummy-fallback response (ANALYZE_FALLBACK_HEADER present) must
// NEVER clear the pending requestId — only a confirmed real success
// (no fallback header) may.
describe("app/page.tsx's post-/api/analyze requestId handling (不具合A regression)", () => {
  beforeEach(() => {
    vi.stubGlobal("window", makeFakeWindow());
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  /** Mirrors app/page.tsx:286-316's exact sequence for a response
   * that was `response.ok` — the only branch 不具合A touched. */
  function simulateOkResponseHandling(isDummyFallback: boolean) {
    if (isDummyFallback) {
      // (setFallbackMessage(...) in the real code — no storage effect)
    } else {
      clearPendingSyncAnalysisRequest();
    }
  }

  it("keeps the same requestId after a dummy-fallback (200 + ANALYZE_FALLBACK_HEADER) response", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const firstRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-1",
    );

    simulateOkResponseHandling(/* isDummyFallback */ true);

    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-2",
    );
    expect(secondRequestId).toBe(firstRequestId);
  });

  it("clears the requestId after a confirmed real success (200, no fallback header)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const firstRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-1",
    );

    simulateOkResponseHandling(/* isDummyFallback */ false);

    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-2",
    );
    expect(secondRequestId).toBe("generated-2");
    expect(secondRequestId).not.toBe(firstRequestId);
  });

  it("resubmitting the exact same input after a fallback reuses the same requestId (never a fresh/duplicate execution)", () => {
    const firstBody = buildAnalyzeRequestBody("Acme", []);
    const firstRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      firstBody,
      () => "generated-1",
    );
    simulateOkResponseHandling(true);

    // The user resubmits with identical input (same brand, no edits).
    const secondBody = buildAnalyzeRequestBody("Acme", []);
    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      secondBody,
      () => "generated-2",
    );

    expect(secondRequestId).toBe(firstRequestId);
  });

  it("still issues a fresh requestId when the input genuinely changes after a fallback", () => {
    const firstBody = buildAnalyzeRequestBody("Acme", []);
    resolveRequestIdForSyncAnalysis("user-1", "project-1", firstBody, () => "generated-1");
    simulateOkResponseHandling(true);

    const differentBody = buildAnalyzeRequestBody("DifferentBrand", []);
    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      differentBody,
      () => "generated-2",
    );
    expect(secondRequestId).toBe("generated-2");
  });

  it("a terminal 409 (previously failed) still clears the requestId even though it's also a kept-alive concern for still-running", () => {
    // Regression guard: 不具合A's fix only touches the response.ok
    // branch — the existing 409 handling (isTerminalAnalyzeConflictCode)
    // must be unaffected.
    const body = buildAnalyzeRequestBody("Acme", []);
    const firstRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-1",
    );
    expect(isTerminalAnalyzeConflictCode("analysis_previously_failed")).toBe(true);
    clearPendingSyncAnalysisRequest();

    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-2",
    );
    expect(secondRequestId).not.toBe(firstRequestId);
  });

  it("a still-running 409 keeps the requestId (isTerminalAnalyzeConflictCode is false, so no clear happens)", () => {
    const body = buildAnalyzeRequestBody("Acme", []);
    const firstRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-1",
    );
    expect(isTerminalAnalyzeConflictCode("analysis_still_running")).toBe(false);
    // app/page.tsx only calls clearPendingSyncAnalysisRequest() here
    // when isTerminalAnalyzeConflictCode(code) is true — simulate the
    // "false" branch by simply not calling it.

    const secondRequestId = resolveRequestIdForSyncAnalysis(
      "user-1",
      "project-1",
      body,
      () => "generated-2",
    );
    expect(secondRequestId).toBe(firstRequestId);
  });
});

describe("getAnalyzeConflictMessage / isTerminalAnalyzeConflictCode", () => {
  it("returns a still-running-specific message and treats it as non-terminal", () => {
    expect(getAnalyzeConflictMessage(ANALYZE_STILL_RUNNING_CODE)).toContain("処理中");
    expect(isTerminalAnalyzeConflictCode(ANALYZE_STILL_RUNNING_CODE)).toBe(false);
  });

  it("returns a previously-failed-specific message and treats it as terminal", () => {
    expect(getAnalyzeConflictMessage(ANALYZE_PREVIOUSLY_FAILED_CODE)).toContain("失敗");
    expect(isTerminalAnalyzeConflictCode(ANALYZE_PREVIOUSLY_FAILED_CODE)).toBe(true);
  });

  it("treats a request conflict and a cancelled request as terminal", () => {
    expect(isTerminalAnalyzeConflictCode(ANALYZE_REQUEST_CONFLICT_CODE)).toBe(true);
    expect(isTerminalAnalyzeConflictCode(ANALYZE_REQUEST_CANCELLED_CODE)).toBe(true);
  });

  it("falls back to a generic message and treats an unrecognized/missing code as non-terminal", () => {
    expect(getAnalyzeConflictMessage(null)).toBe(ANALYZE_CONFLICT_GENERIC_MESSAGE);
    expect(getAnalyzeConflictMessage("some_unknown_code")).toBe(ANALYZE_CONFLICT_GENERIC_MESSAGE);
    expect(isTerminalAnalyzeConflictCode(null)).toBe(false);
    expect(isTerminalAnalyzeConflictCode("some_unknown_code")).toBe(false);
  });
});

describe("getAnalyzeFallbackMessage", () => {
  it("returns a timeout-specific message that mentions history may still have the real result", () => {
    // Reworded per improve/history-centered-analysis-flow — no longer
    // calls the dummy data "開発用データ" (that wording made this
    // screen read like a dev/test artifact); says "一時的なプレビュー"
    // instead and still points the reader at the history list.
    const message = getAnalyzeFallbackMessage("timeout");

    expect(message).toContain("プレビュー");
    expect(message).toContain("履歴一覧");
    expect(message).not.toContain("開発用データ");
  });

  it("returns a distinct message for not_configured", () => {
    expect(getAnalyzeFallbackMessage("not_configured")).toContain("設定されていない");
  });

  it("returns a generic failure message for every other known reason", () => {
    for (const reason of ["request_failed", "upstream_error", "invalid_json", "schema_mismatch"]) {
      expect(getAnalyzeFallbackMessage(reason)).toContain("開発用データ");
    }
  });

  it("falls back to a generic message for an unrecognized or null reason", () => {
    expect(getAnalyzeFallbackMessage(null)).toContain("開発用データ");
    expect(getAnalyzeFallbackMessage("something-unexpected")).toContain("開発用データ");
  });
});
