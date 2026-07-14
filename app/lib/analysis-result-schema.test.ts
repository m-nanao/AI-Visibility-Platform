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
      expect(result.data.meta.documentsSource).toBe("development_sample");
      expect(result.data.meta.sections.cooccurrenceRanking).toBe("mock");
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

  it("rejects a response with an invalid meta.documentsSource value", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        sections: {
          summary: "mock",
          cooccurrenceRanking: "mock",
          contextAnalysis: "mock",
          aiOverviewComparison: "mock",
          improvements: "mock",
        },
        documentsSource: "not_a_real_source",
        generatedAt: "2026-07-10T00:00:00.000Z",
      },
    };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response with a malformed generatedAt", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        generatedAt: "not-a-date",
      },
    };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
  });

  it("accepts meta.urlFetchResults: null (Pydantic's JSON serialization of an unset optional field)", () => {
    // Regression test: Python's `list[UrlFetchResult] | None = None`
    // serializes to JSON `null`, not an absent key, when unset. This
    // must not be treated as a schema mismatch.
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: { ...buildDummyAnalysis("OpenAI").meta, urlFetchResults: null },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.urlFetchResults).toBeUndefined();
    }
  });

  it("accepts urlFetchResults[].error: null the same way", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        urlFetchResults: [{ url: "https://example.com", success: true, error: null }],
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.urlFetchResults?.[0].error).toBeUndefined();
    }
  });

  it("accepts \"unavailable\" as a valid section status", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        sections: {
          ...buildDummyAnalysis("OpenAI").meta.sections,
          cooccurrenceRanking: "unavailable",
        },
        documentsSource: "web_fetch",
        urlFetchResults: [
          { url: "http://localhost/x", success: false, error: "resolves to a disallowed address: 127.0.0.1" },
        ],
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.sections.cooccurrenceRanking).toBe("unavailable");
    }
  });

  it("rejects a section status outside mock/real/unavailable", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        sections: {
          ...buildDummyAnalysis("OpenAI").meta.sections,
          cooccurrenceRanking: "not_a_real_status",
        },
      },
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
