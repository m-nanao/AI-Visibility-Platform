import { afterEach, describe, expect, it } from "vitest";
import { buildAnalyzeRequestBody, isAiOverviewModeSelectorEnabled } from "./analysis-request";

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

  it("includes both urls and aiOverviewMode together", () => {
    expect(
      buildAnalyzeRequestBody("Acme", ["https://acme.example.com"], "dataforseo"),
    ).toEqual({
      brandName: "Acme",
      urls: ["https://acme.example.com"],
      aiOverviewMode: "dataforseo",
    });
  });
});
