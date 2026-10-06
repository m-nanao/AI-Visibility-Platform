import { describe, expect, it } from "vitest";
import {
  parseAnalysisRunComparisonResponse,
  parseAnalysisRunDetailResponse,
  parseAnalysisRunListResponse,
  parseGeminiRerunResponse,
} from "./analysis-history-schema";

function validDetailResponse() {
  return {
    id: "11111111-1111-1111-1111-111111111111",
    brand: {
      id: "22222222-2222-2222-2222-222222222222",
      name: "サイボウズ",
      canonicalDomain: "cybozu.co.jp",
    },
    run: {
      status: "completed",
      inputSnapshot: { brandName: "サイボウズ" },
      sourceSummary: { web_fetch: 1, common_crawl: 3 },
      startedAt: "2026-09-09T00:00:00+09:00",
      completedAt: "2026-09-09T00:00:10+09:00",
    },
    result: { brandSummary: {}, cooccurrenceRanking: [] },
    meta: { documentsSource: "development_sample" },
  };
}

function validListResponse() {
  return {
    items: [
      {
        id: "11111111-1111-1111-1111-111111111111",
        brandName: "サイボウズ",
        canonicalDomain: "cybozu.co.jp",
        status: "completed",
        visibilityScore: 86,
        sourceSummary: { web_fetch: 1, common_crawl: 3 },
        startedAt: "2026-09-09T00:00:00+09:00",
        completedAt: "2026-09-09T00:00:10+09:00",
        createdAt: "2026-09-09T00:00:10+09:00",
      },
    ],
    limit: 20,
    offset: 0,
    total: null,
  };
}

describe("parseAnalysisRunListResponse", () => {
  it("accepts a well-formed AnalysisRunListResponse", () => {
    const result = parseAnalysisRunListResponse(validListResponse());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items).toHaveLength(1);
      expect(result.data.items[0].brandName).toBe("サイボウズ");
      expect(result.data.total).toBeNull();
    }
  });

  it("accepts null optional fields (Pydantic's X | None = None serializes as null)", () => {
    const withNulls = {
      items: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          brandName: "サイボウズ",
          canonicalDomain: null,
          status: "completed",
          visibilityScore: null,
          sourceSummary: null,
          startedAt: null,
          completedAt: null,
          createdAt: null,
        },
      ],
      limit: 20,
      offset: 0,
      total: null,
    };

    const result = parseAnalysisRunListResponse(withNulls);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].canonicalDomain).toBeUndefined();
      expect(result.data.items[0].sourceSummary).toBeUndefined();
    }
  });

  it("accepts an empty items array", () => {
    const empty = { items: [], limit: 20, offset: 0, total: null };

    const result = parseAnalysisRunListResponse(empty);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items).toHaveLength(0);
    }
  });

  it("does not require or depend on result/resultJson (list API never returns them)", () => {
    // A detail-shaped payload happens to include `result`/`meta` at the
    // item level here just to prove parsing succeeds without them and
    // that the parsed item type has no such field — the list schema
    // must never assume result_json is present.
    const withExtraFields = {
      items: [
        {
          id: "11111111-1111-1111-1111-111111111111",
          brandName: "サイボウズ",
          canonicalDomain: "cybozu.co.jp",
          status: "completed",
          visibilityScore: 86,
          sourceSummary: { web_fetch: 1 },
          startedAt: "2026-09-09T00:00:00+09:00",
          completedAt: "2026-09-09T00:00:10+09:00",
          createdAt: "2026-09-09T00:00:10+09:00",
          result: { brandSummary: {} },
          resultJson: { brandSummary: {} },
        },
      ],
      limit: 20,
      offset: 0,
      total: null,
    };

    const result = parseAnalysisRunListResponse(withExtraFields);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0]).not.toHaveProperty("result");
      expect(result.data.items[0]).not.toHaveProperty("resultJson");
    }
  });

  it("rejects a response missing required fields", () => {
    const invalid = { items: [{ brandName: "サイボウズ" }] };

    const result = parseAnalysisRunListResponse(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response with the wrong field types", () => {
    const invalid = {
      ...validListResponse(),
      limit: "20",
    };

    const result = parseAnalysisRunListResponse(invalid);

    expect(result.success).toBe(false);
  });

  // --- modeSummary (feature/history-delete-and-mode-badges) ---

  it("accepts an item with modeSummary", () => {
    const withModeSummary = {
      ...validListResponse(),
      items: [
        {
          ...validListResponse().items[0],
          modeSummary: {
            aiOverview: "live",
            chatgpt: "real",
            claude: "off",
            gemini: "unavailable",
            commonCrawl: "real",
          },
        },
      ],
    };

    const result = parseAnalysisRunListResponse(withModeSummary);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].modeSummary).toEqual({
        aiOverview: "live",
        chatgpt: "real",
        claude: "off",
        gemini: "unavailable",
        commonCrawl: "real",
      });
    }
  });

  it("accepts an item without modeSummary (older saved history)", () => {
    const result = parseAnalysisRunListResponse(validListResponse());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].modeSummary).toBeUndefined();
    }
  });

  it("accepts modeSummary: null the same way as other optional fields", () => {
    const withNullModeSummary = {
      ...validListResponse(),
      items: [{ ...validListResponse().items[0], modeSummary: null }],
    };

    const result = parseAnalysisRunListResponse(withNullModeSummary);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].modeSummary).toBeUndefined();
    }
  });

  it("rejects a modeSummary missing one of its required keys", () => {
    const invalid = {
      ...validListResponse(),
      items: [
        {
          ...validListResponse().items[0],
          modeSummary: { aiOverview: "live", chatgpt: "real" },
        },
      ],
    };

    const result = parseAnalysisRunListResponse(invalid);

    expect(result.success).toBe(false);
  });

  // --- sourceUrls (fix/history-domain-search) ---

  it("accepts an item with sourceUrls", () => {
    const withSourceUrls = {
      ...validListResponse(),
      items: [
        { ...validListResponse().items[0], sourceUrls: ["https://www.cybozu.co.jp/"] },
      ],
    };

    const result = parseAnalysisRunListResponse(withSourceUrls);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].sourceUrls).toEqual(["https://www.cybozu.co.jp/"]);
    }
  });

  it("defaults sourceUrls to [] when the key is absent (backend predating this field)", () => {
    const result = parseAnalysisRunListResponse(validListResponse());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].sourceUrls).toEqual([]);
    }
  });

  it("accepts an empty sourceUrls array (development_sample-only run)", () => {
    const withEmptySourceUrls = {
      ...validListResponse(),
      items: [{ ...validListResponse().items[0], sourceUrls: [] }],
    };

    const result = parseAnalysisRunListResponse(withEmptySourceUrls);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.items[0].sourceUrls).toEqual([]);
    }
  });

  it("rejects sourceUrls with a non-string entry", () => {
    const invalid = {
      ...validListResponse(),
      items: [{ ...validListResponse().items[0], sourceUrls: [123] }],
    };

    const result = parseAnalysisRunListResponse(invalid);

    expect(result.success).toBe(false);
  });
});

describe("parseAnalysisRunDetailResponse", () => {
  it("accepts a well-formed AnalysisRunDetailResponse", () => {
    const result = parseAnalysisRunDetailResponse(validDetailResponse());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.brand.name).toBe("サイボウズ");
      expect(result.data.run.status).toBe("completed");
      expect(result.data.result).toEqual({ brandSummary: {}, cooccurrenceRanking: [] });
    }
  });

  it("accepts null optional fields (canonicalDomain, sourceSummary, completedAt, meta)", () => {
    const withNulls = {
      ...validDetailResponse(),
      brand: { ...validDetailResponse().brand, canonicalDomain: null },
      run: {
        ...validDetailResponse().run,
        sourceSummary: null,
        completedAt: null,
      },
      meta: null,
    };

    const result = parseAnalysisRunDetailResponse(withNulls);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.brand.canonicalDomain).toBeUndefined();
      expect(result.data.run.sourceSummary).toBeUndefined();
      expect(result.data.meta).toBeUndefined();
    }
  });

  it("accepts any result shape without validating it against AnalysisResult (validated separately)", () => {
    const withOldResultShape = {
      ...validDetailResponse(),
      result: { some: "completely different shape from a future task" },
    };

    const result = parseAnalysisRunDetailResponse(withOldResultShape);

    expect(result.success).toBe(true);
  });

  it("rejects a response missing required fields", () => {
    const invalid = { id: "11111111-1111-1111-1111-111111111111" };

    const result = parseAnalysisRunDetailResponse(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response with the wrong field types", () => {
    const invalid = {
      ...validDetailResponse(),
      run: { ...validDetailResponse().run, status: 123 },
    };

    const result = parseAnalysisRunDetailResponse(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response missing run.inputSnapshot (required on the backend model)", () => {
    const invalid = {
      ...validDetailResponse(),
      run: { status: "completed", startedAt: "2026-09-09T00:00:00+09:00" },
    };

    const result = parseAnalysisRunDetailResponse(invalid);

    expect(result.success).toBe(false);
  });
});

function validComparisonResponseWithPrevious() {
  return {
    current: {
      id: "11111111-1111-1111-1111-111111111111",
      startedAt: "2026-09-10T00:00:00+09:00",
      visibilityScore: 91,
    },
    previous: {
      id: "22222222-2222-2222-2222-222222222222",
      startedAt: "2026-09-01T00:00:00+09:00",
      visibilityScore: 86,
    },
    diff: {
      visibilityScore: { current: 91, previous: 86, delta: 5 },
      cooccurrence: {
        topN: 10,
        newTerms: [{ term: "ChatGPT", rank: 3, score: 12 }],
        removedTerms: [{ term: "広告", rank: 7, score: 5 }],
        changedTerms: [
          {
            term: "SEO",
            currentRank: 2,
            previousRank: 5,
            rankDelta: -3,
            currentScore: 18,
            previousScore: 12,
            scoreDelta: 6,
          },
        ],
      },
      improvements: { currentCount: 4, previousCount: 3, delta: 1 },
    },
    warnings: [],
  };
}

describe("parseAnalysisRunComparisonResponse", () => {
  it("accepts a well-formed response with a previous run", () => {
    const result = parseAnalysisRunComparisonResponse(validComparisonResponseWithPrevious());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.current.visibilityScore).toBe(91);
      expect(result.data.previous?.visibilityScore).toBe(86);
      expect(result.data.diff?.visibilityScore.delta).toBe(5);
      expect(result.data.diff?.cooccurrence.changedTerms[0].rankDelta).toBe(-3);
    }
  });

  it("accepts previous:null and diff:null (no earlier run for this brand yet)", () => {
    const noPrevious = {
      current: {
        id: "11111111-1111-1111-1111-111111111111",
        startedAt: "2026-09-10T00:00:00+09:00",
        visibilityScore: 91,
      },
      previous: null,
      diff: null,
      warnings: ["比較できる過去履歴がまだありません。"],
    };

    const result = parseAnalysisRunComparisonResponse(noPrevious);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.previous).toBeNull();
      expect(result.data.diff).toBeNull();
      expect(result.data.warnings).toEqual(["比較できる過去履歴がまだありません。"]);
    }
  });

  it("accepts current.startedAt/visibilityScore: null (a run whose result is missing/incompatible)", () => {
    const withNullSummary = {
      ...validComparisonResponseWithPrevious(),
      current: { id: "11111111-1111-1111-1111-111111111111", startedAt: null, visibilityScore: null },
    };

    const result = parseAnalysisRunComparisonResponse(withNullSummary);

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.current.startedAt).toBeNull();
      expect(result.data.current.visibilityScore).toBeNull();
    }
  });

  it("rejects a response missing required fields", () => {
    const invalid = { current: { id: "11111111-1111-1111-1111-111111111111" } };

    const result = parseAnalysisRunComparisonResponse(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response with the wrong field types", () => {
    const invalid = {
      ...validComparisonResponseWithPrevious(),
      diff: {
        ...validComparisonResponseWithPrevious().diff,
        visibilityScore: { current: "91", previous: 86, delta: 5 },
      },
    };

    const result = parseAnalysisRunComparisonResponse(invalid);

    expect(result.success).toBe(false);
  });

  it("rejects a response missing warnings", () => {
    const invalid = {
      ...validComparisonResponseWithPrevious(),
      warnings: undefined,
    };

    const result = parseAnalysisRunComparisonResponse(invalid);

    expect(result.success).toBe(false);
  });
});

function validGeminiRerunResponse() {
  return {
    updated: true,
    analysisRunId: "11111111-1111-1111-1111-111111111111",
    result: { brandSummary: {}, cooccurrenceRanking: [] },
  };
}

describe("parseGeminiRerunResponse", () => {
  it("accepts a well-formed GeminiRerunResponse", () => {
    const result = parseGeminiRerunResponse(validGeminiRerunResponse());

    expect(result.success).toBe(true);
    if (result.success) {
      expect(result.data.updated).toBe(true);
      expect(result.data.analysisRunId).toBe("11111111-1111-1111-1111-111111111111");
      expect(result.data.result).toEqual({ brandSummary: {}, cooccurrenceRanking: [] });
    }
  });

  it("accepts any result shape without validating it against AnalysisResult (validated separately)", () => {
    const withOldResultShape = {
      ...validGeminiRerunResponse(),
      result: { some: "completely different shape from a future task" },
    };

    const result = parseGeminiRerunResponse(withOldResultShape);

    expect(result.success).toBe(true);
  });

  it("rejects a response missing required fields", () => {
    const result = parseGeminiRerunResponse({ updated: true });

    expect(result.success).toBe(false);
  });

  it("rejects a response with the wrong field types", () => {
    const invalid = { ...validGeminiRerunResponse(), updated: "yes" };

    const result = parseGeminiRerunResponse(invalid);

    expect(result.success).toBe(false);
  });
});
