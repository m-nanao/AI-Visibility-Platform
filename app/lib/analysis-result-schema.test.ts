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

  it("accepts meta.documentCount and meta.sourceTypes when present", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        documentCount: 3,
        sourceTypes: ["user_provided"],
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.documentCount).toBe(3);
      expect(result.data.meta.sourceTypes).toEqual(["user_provided"]);
    }
  });

  it("accepts meta.documentCount/sourceTypes: null the same way as other optional fields", () => {
    // Same Pydantic-null-vs-absent-key situation as urlFetchResults above.
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        documentCount: null,
        sourceTypes: null,
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.documentCount).toBeUndefined();
      expect(result.data.meta.sourceTypes).toBeUndefined();
    }
  });

  it("accepts meta.chunkCount when present", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: { ...buildDummyAnalysis("OpenAI").meta, chunkCount: 4 },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.chunkCount).toBe(4);
    }
  });

  it("accepts meta.chunkCount: null the same way as other optional fields", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: { ...buildDummyAnalysis("OpenAI").meta, chunkCount: null },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.chunkCount).toBeUndefined();
    }
  });

  it("accepts meta.claudeProvider/meta.geminiProvider when present", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        claudeProvider: {
          mode: "anthropic",
          status: "real",
          reason: "Claude Anthropic API request succeeded.",
          environment: "api",
        },
        geminiProvider: {
          mode: "google",
          status: "real",
          reason: "Gemini Google API request succeeded.",
          environment: "api",
        },
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.claudeProvider?.mode).toBe("anthropic");
      expect(result.data.meta.geminiProvider?.mode).toBe("google");
    }
  });

  it("accepts a response that omits meta.claudeProvider/meta.geminiProvider entirely (old saved history)", () => {
    // Analysis history saved before this feature existed has no
    // claudeProvider/geminiProvider key at all in its stored meta_json
    // — this must still parse successfully (see
    // docs/36_multi_ai_comparison_design.md's backward-compatibility
    // requirement).
    const oldMeta = { ...buildDummyAnalysis("OpenAI").meta };
    const valid = { ...buildDummyAnalysis("OpenAI"), meta: oldMeta };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.claudeProvider).toBeUndefined();
      expect(result.data.meta.geminiProvider).toBeUndefined();
    }
  });

  it("accepts meta.claudeProvider/meta.geminiProvider: null the same way as other optional fields", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        claudeProvider: null,
        geminiProvider: null,
      },
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.meta.claudeProvider).toBeUndefined();
      expect(result.data.meta.geminiProvider).toBeUndefined();
    }
  });

  it("rejects a sourceTypes value outside the known DocumentSourceType set", () => {
    const invalid = {
      ...buildDummyAnalysis("OpenAI"),
      meta: {
        ...buildDummyAnalysis("OpenAI").meta,
        sourceTypes: ["not_a_real_source_type"],
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

  // analysisRunId (docs/23_analysis_run_id_and_post_analyze_link_design.md)

  it("accepts an AnalysisResult without analysisRunId (older saved results predating this field)", () => {
    const valid = buildDummyAnalysis("OpenAI");
    expect("analysisRunId" in valid).toBe(false);

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.analysisRunId).toBeUndefined();
    }
  });

  it("accepts analysisRunId: null (DB save disabled/unconfigured/failed)", () => {
    const valid = { ...buildDummyAnalysis("OpenAI"), analysisRunId: null };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      // Unlike other optional fields, null is preserved (not
      // normalized to undefined) to match `analysisRunId?: string | null`.
      expect(result.data.analysisRunId).toBeNull();
    }
  });

  it("accepts analysisRunId as a valid UUID string (DB save succeeded)", () => {
    const analysisRunId = "550e8400-e29b-41d4-a716-446655440000";
    const valid = { ...buildDummyAnalysis("OpenAI"), analysisRunId };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.analysisRunId).toBe(analysisRunId);
    }
  });

  it("rejects a non-UUID analysisRunId string", () => {
    const invalid = { ...buildDummyAnalysis("OpenAI"), analysisRunId: "not-a-uuid" };

    const result = parseAnalysisResult(invalid);

    expect(result.success).toBe(false);
  });

  // --- Gemini truncation-detection fields (finishReason/isTruncated/note) ---

  it("accepts aiOverviewComparison items with finishReason/isTruncated/note (Gemini truncation)", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Gemini (Google API)",
          mentioned: true,
          rank: null,
          summary: "OpenAI is a well-known...",
          finishReason: "MAX_TOKENS",
          isTruncated: true,
          note: "Gemini APIの出力が途中で終了した可能性があります。",
        },
      ],
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      const item = result.data.aiOverviewComparison[0];
      expect(item.finishReason).toBe("MAX_TOKENS");
      expect(item.isTruncated).toBe(true);
      expect(item.note).toBe("Gemini APIの出力が途中で終了した可能性があります。");
    }
  });

  it("accepts aiOverviewComparison items that omit finishReason/isTruncated/note (old saved history)", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        { platform: "Gemini (Google API)", mentioned: true, rank: null, summary: "OpenAI is..." },
      ],
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      const item = result.data.aiOverviewComparison[0];
      expect(item.finishReason).toBeUndefined();
      expect(item.isTruncated).toBeUndefined();
      expect(item.note).toBeUndefined();
    }
  });

  it("accepts aiOverviewComparison items with finishReason/isTruncated/note: null the same way as other optional fields", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Gemini (Google API)",
          mentioned: true,
          rank: null,
          summary: "OpenAI is...",
          finishReason: null,
          isTruncated: null,
          note: null,
        },
      ],
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      const item = result.data.aiOverviewComparison[0];
      expect(item.finishReason).toBeUndefined();
      expect(item.isTruncated).toBeUndefined();
      expect(item.note).toBeUndefined();
    }
  });

  it("accepts isTruncated: false with no note (a normal, non-truncated Gemini success)", () => {
    const valid = {
      ...buildDummyAnalysis("OpenAI"),
      aiOverviewComparison: [
        {
          platform: "Gemini (Google API)",
          mentioned: true,
          rank: null,
          summary: "OpenAI is...",
          finishReason: "STOP",
          isTruncated: false,
        },
      ],
    };

    const result = parseAnalysisResult(valid);

    expect(result.success).toBe(true);
    if (result.success) {
      const item = result.data.aiOverviewComparison[0];
      expect(item.finishReason).toBe("STOP");
      expect(item.isTruncated).toBe(false);
      expect(item.note).toBeUndefined();
    }
  });
});
