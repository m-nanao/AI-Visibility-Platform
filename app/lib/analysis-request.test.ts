import { afterEach, describe, expect, it } from "vitest";
import {
  buildAnalyzeRequestBody,
  isAiOverviewModeSelectorEnabled,
  isChatGptModeSelectorEnabled,
  isCommonCrawlModeSelectorEnabled,
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
});
