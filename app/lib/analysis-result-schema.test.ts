import { describe, expect, it } from "vitest";
import { parseAnalysisResult } from "./analysis-result-schema";
import { buildDummyAnalysis } from "./dummy-data";

describe("parseAnalysisResult", () => {
  it("accepts a well-formed AnalysisResult", () => {
    const valid = buildDummyAnalysis("OpenAI");

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.brandName).toBe("OpenAI");
      expect(result.data.meta.source).toBe("nextjs_mock");
    }
  });

  it("rejects a response missing required fields", () => {
    const invalid = { brandName: "OpenAI" };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.reason).toContain("summary");
    }
  });

  it("rejects a response with the wrong field types", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      summary: { ...buildDummyAnalysis("OpenAI").summary, visibilityScore: "high" },
    };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response with an invalid meta.source value", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: { source: "not_a_real_source", isMock: true, generatedAt: "2026-07-10" },
    };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
  });

  it("never leaks the offending values in the failure reason", () => {
    const invalid = { ...buildDummyAnalysis("OpenAI"), brandName: 42 };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
    if (!result.success) {
      expect(result.reason).not.toContain("42");
    }
  });
});
