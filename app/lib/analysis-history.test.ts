import { describe, expect, it } from "vitest";
import {
  HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
  HISTORY_COMPARISON_NOT_FOUND_MESSAGE,
  HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE,
  HISTORY_DETAIL_GENERIC_ERROR_MESSAGE,
  HISTORY_DETAIL_INCOMPATIBLE_MESSAGE,
  HISTORY_DETAIL_NOT_FOUND_MESSAGE,
  HISTORY_DISABLED_MESSAGE,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_FORBIDDEN_MESSAGE,
  HISTORY_GENERIC_ERROR_MESSAGE,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  HISTORY_PAGE_TITLE,
  buildHistoryDetailPath,
  formatAnalysisRunDetailBasicInfo,
  formatAnalysisRunListItem,
  formatComparisonImprovementsLabel,
  formatComparisonVisibilityScoreLabel,
  formatCooccurrenceChangedTermLabel,
  formatCooccurrenceNewTermLabel,
  formatCooccurrenceRemovedTermLabel,
  formatSignedDelta,
  formatSourceSummary,
  getStatusLabel,
  limitComparisonTerms,
  resolveHistoryComparisonFetchOutcome,
  resolveHistoryDetailFetchOutcome,
  resolveHistoryFetchOutcome,
  resolvePostAnalyzeHistoryLink,
} from "./analysis-history";
import type {
  AnalysisRunComparisonResponse,
  AnalysisRunDetailResponse,
  AnalysisRunListItem,
} from "./analysis-history";
import { buildDummyAnalysis } from "./dummy-data";

const SAMPLE_ITEM: AnalysisRunListItem = {
  id: "11111111-1111-1111-1111-111111111111",
  brandName: "サイボウズ",
  canonicalDomain: "cybozu.co.jp",
  status: "completed",
  visibilityScore: 86,
  sourceSummary: { web_fetch: 1, common_crawl: 3 },
  startedAt: "2026-09-09T00:00:00+09:00",
  completedAt: "2026-09-09T00:00:10+09:00",
  createdAt: "2026-09-09T00:00:10+09:00",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("HISTORY_PAGE_TITLE", () => {
  it("is the Japanese heading used on /history", () => {
    expect(HISTORY_PAGE_TITLE).toBe("分析履歴");
  });
});

describe("getStatusLabel", () => {
  it("maps known statuses to Japanese labels", () => {
    expect(getStatusLabel("completed")).toBe("完了");
    expect(getStatusLabel("partial")).toBe("一部完了");
    expect(getStatusLabel("failed")).toBe("失敗");
    expect(getStatusLabel("running")).toBe("実行中");
    expect(getStatusLabel("queued")).toBe("待機中");
  });

  it("falls back to the raw status string for an unknown value", () => {
    expect(getStatusLabel("something_new")).toBe("something_new");
  });
});

describe("formatSourceSummary", () => {
  it("joins entries as 'type: count / type: count'", () => {
    expect(formatSourceSummary({ web_fetch: 1, common_crawl: 3 })).toBe(
      "web_fetch: 1 / common_crawl: 3",
    );
  });

  it("returns undefined for undefined input", () => {
    expect(formatSourceSummary(undefined)).toBeUndefined();
  });

  it("returns undefined for an empty object", () => {
    expect(formatSourceSummary({})).toBeUndefined();
  });
});

describe("formatAnalysisRunListItem", () => {
  it("formats brand name, status, visibility score, and source summary", () => {
    const display = formatAnalysisRunListItem(SAMPLE_ITEM);

    expect(display.brandNameLabel).toBe("サイボウズ");
    expect(display.canonicalDomainLabel).toBe("cybozu.co.jp");
    expect(display.statusLabel).toBe("完了");
    expect(display.visibilityScoreLabel).toBe("可視性スコア 86");
    expect(display.sourceSummaryLabel).toBe("web_fetch: 1 / common_crawl: 3");
    expect(display.startedAtLabel).toBe("2026-09-09T00:00:00+09:00");
  });

  it("omits visibilityScoreLabel/sourceSummaryLabel when absent", () => {
    const display = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "partial",
    });

    expect(display.visibilityScoreLabel).toBeUndefined();
    expect(display.sourceSummaryLabel).toBeUndefined();
  });

  it("falls back to createdAt, then a placeholder, for startedAtLabel", () => {
    const withCreatedOnly = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
      createdAt: "2026-09-09T00:00:10+09:00",
    });
    expect(withCreatedOnly.startedAtLabel).toBe("2026-09-09T00:00:10+09:00");

    const withNeither = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
    });
    expect(withNeither.startedAtLabel).toBe("実行日時不明");
  });
});

describe("resolveHistoryFetchOutcome", () => {
  it("returns a disabled view when the response is 503 (READ_HISTORY_ENABLED=false etc.)", async () => {
    const outcome = await resolveHistoryFetchOutcome(
      jsonResponse({ error: "analysis history read API is not enabled" }, 503),
    );

    expect(outcome.kind).toBe("disabled");
    if (outcome.kind === "disabled") {
      expect(outcome.message).toBe(HISTORY_DISABLED_MESSAGE);
    }
  });

  it("returns a forbidden view when the response is 403 (HISTORY_READ_TOKEN gate rejected the request)", async () => {
    const outcome = await resolveHistoryFetchOutcome(
      jsonResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE });
  });

  it("returns an error view when the network request itself failed (response is null)", async () => {
    const outcome = await resolveHistoryFetchOutcome(null);

    expect(outcome).toEqual({ kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE });
  });

  it("returns an error view for a non-503/403 failure status", async () => {
    const outcome = await resolveHistoryFetchOutcome(
      jsonResponse({ error: "something went wrong" }, 502),
    );

    expect(outcome).toEqual({ kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE });
  });

  it("returns an error view when the body fails schema validation", async () => {
    const outcome = await resolveHistoryFetchOutcome(jsonResponse({ not: "valid" }, 200));

    expect(outcome).toEqual({ kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE });
  });

  it("returns an empty view when items is an empty array", async () => {
    const outcome = await resolveHistoryFetchOutcome(
      jsonResponse({ items: [], limit: 20, offset: 0, total: null }, 200),
    );

    expect(outcome).toEqual({ kind: "empty" });
  });

  it("returns an items view with the parsed items when items is non-empty", async () => {
    const outcome = await resolveHistoryFetchOutcome(
      jsonResponse({ items: [SAMPLE_ITEM], limit: 20, offset: 0, total: null }, 200),
    );

    expect(outcome.kind).toBe("items");
    if (outcome.kind === "items") {
      expect(outcome.items).toHaveLength(1);
      expect(outcome.items[0].brandName).toBe("サイボウズ");
    }
  });

  it("empty-state text is distinct from the disabled message (0 items vs. read API off)", () => {
    expect(HISTORY_EMPTY_STATE_TEXT).not.toBe(HISTORY_DISABLED_MESSAGE);
  });
});

describe("buildHistoryDetailPath", () => {
  it("builds a /history/{id} path", () => {
    expect(buildHistoryDetailPath("11111111-1111-1111-1111-111111111111")).toBe(
      "/history/11111111-1111-1111-1111-111111111111",
    );
  });

  it("encodes characters that would otherwise be interpreted as path segments", () => {
    expect(buildHistoryDetailPath("a/b")).toBe("/history/a%2Fb");
  });
});

describe("HISTORY_LIST_DETAIL_LINK_TEXT", () => {
  it("replaces the earlier 'detail is a future task' placeholder", () => {
    expect(HISTORY_LIST_DETAIL_LINK_TEXT).toBe("詳細を見る");
  });
});

const SAMPLE_DETAIL: AnalysisRunDetailResponse = {
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
  result: buildDummyAnalysis("サイボウズ") as unknown as Record<string, unknown>,
  meta: { documentsSource: "development_sample" },
};

function jsonDetailResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("formatAnalysisRunDetailBasicInfo", () => {
  it("formats brand/run info and visibilityScore from a parsed result", () => {
    const parsedResult = buildDummyAnalysis("サイボウズ");
    const display = formatAnalysisRunDetailBasicInfo(SAMPLE_DETAIL, parsedResult);

    expect(display.brandNameLabel).toBe("サイボウズ");
    expect(display.canonicalDomainLabel).toBe("cybozu.co.jp");
    expect(display.statusLabel).toBe("完了");
    expect(display.startedAtLabel).toBe("2026-09-09T00:00:00+09:00");
    expect(display.sourceSummaryLabel).toBe("web_fetch: 1 / common_crawl: 3");
    expect(display.visibilityScoreLabel).toBe(
      `可視性スコア ${parsedResult.summary.visibilityScore}`,
    );
  });

  it("omits visibilityScoreLabel when no parsed result is given (e.g. incompatible outcome)", () => {
    const display = formatAnalysisRunDetailBasicInfo(SAMPLE_DETAIL);

    expect(display.visibilityScoreLabel).toBeUndefined();
    // Brand/run-derived fields are still available independent of `result`.
    expect(display.brandNameLabel).toBe("サイボウズ");
    expect(display.statusLabel).toBe("完了");
  });
});

describe("resolveHistoryDetailFetchOutcome", () => {
  it("returns a disabled view when the response is 503", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ error: "analysis history read API is not enabled" }, 503),
    );

    expect(outcome.kind).toBe("disabled");
    if (outcome.kind === "disabled") {
      expect(outcome.message).toBe(HISTORY_DISABLED_MESSAGE);
    }
  });

  it("returns a forbidden view when the response is 403 (HISTORY_READ_TOKEN gate rejected the request)", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE });
  });

  it("returns a notFound view when the response is 404", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ error: "analysis run not found" }, 404),
    );

    expect(outcome).toEqual({ kind: "notFound", message: HISTORY_DETAIL_NOT_FOUND_MESSAGE });
  });

  it("returns an error view when the network request itself failed (response is null)", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(null);

    expect(outcome).toEqual({ kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE });
  });

  it("returns an error view for a non-503/404 failure status", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ error: "something went wrong" }, 502),
    );

    expect(outcome).toEqual({ kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE });
  });

  it("returns an error view when the envelope fails schema validation", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ not: "valid" }, 200),
    );

    expect(outcome).toEqual({ kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE });
  });

  it("returns an incompatible view when result doesn't match the current AnalysisResult shape", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(
      jsonDetailResponse({ ...SAMPLE_DETAIL, result: { some: "old shape" } }, 200),
    );

    expect(outcome).toEqual({
      kind: "incompatible",
      message: HISTORY_DETAIL_INCOMPATIBLE_MESSAGE,
    });
  });

  it("returns a success view with the parsed detail and result when everything validates", async () => {
    const outcome = await resolveHistoryDetailFetchOutcome(jsonDetailResponse(SAMPLE_DETAIL, 200));

    expect(outcome.kind).toBe("success");
    if (outcome.kind === "success") {
      expect(outcome.detail.brand.name).toBe("サイボウズ");
      expect(outcome.result.brandName).toBe("サイボウズ");
    }
  });

  it("never assumes result/resultJson is present on the list schema (list and detail are independent)", () => {
    // Sanity check that the detail fixture actually carries a `result`
    // field the list schema never has (see
    // app/lib/analysis-history-schema.test.ts's equivalent check on
    // the list side).
    expect(SAMPLE_DETAIL).toHaveProperty("result");
  });
});

describe("resolvePostAnalyzeHistoryLink", () => {
  it("returns a /history/{id} path when analysisRunId is a saved id", () => {
    const link = resolvePostAnalyzeHistoryLink("11111111-1111-1111-1111-111111111111");

    expect(link).toEqual({ path: "/history/11111111-1111-1111-1111-111111111111" });
  });

  it("returns null when analysisRunId is null (DB save disabled/unconfigured/failed)", () => {
    expect(resolvePostAnalyzeHistoryLink(null)).toBeNull();
  });

  it("returns null when analysisRunId is undefined (older saved results predating this field)", () => {
    expect(resolvePostAnalyzeHistoryLink(undefined)).toBeNull();
  });

  it("returns null when analysisRunId is an empty string", () => {
    expect(resolvePostAnalyzeHistoryLink("")).toBeNull();
  });

  it("URL-encodes the analysisRunId via buildHistoryDetailPath", () => {
    // analysisRunId is expected to be a UUID and never need encoding in
    // practice, but the link generation reuses buildHistoryDetailPath()
    // rather than string-concatenating the path, so this stays correct
    // even if that assumption is ever wrong.
    const link = resolvePostAnalyzeHistoryLink("has space");

    expect(link).toEqual({ path: buildHistoryDetailPath("has space") });
    expect(link?.path).toBe("/history/has%20space");
  });
});

// --- History comparison (docs/25_analysis_history_comparison_design.md) ---

function jsonComparisonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const SAMPLE_COMPARISON: AnalysisRunComparisonResponse = {
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

describe("resolveHistoryComparisonFetchOutcome", () => {
  it("returns a disabled view when the response is 503", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({ error: "analysis history read API is not enabled" }, 503),
    );

    expect(outcome).toEqual({ kind: "disabled", message: HISTORY_DISABLED_MESSAGE });
  });

  it("returns a forbidden view when the response is 403", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE });
  });

  it("returns a notFound view when the response is 404", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({ error: "analysis run not found" }, 404),
    );

    expect(outcome).toEqual({
      kind: "notFound",
      message: HISTORY_COMPARISON_NOT_FOUND_MESSAGE,
    });
  });

  it("returns an error view when the network request itself failed (response is null)", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(null);

    expect(outcome).toEqual({
      kind: "error",
      message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
    });
  });

  it("returns an error view for a non-503/403/404 failure status", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({ error: "something went wrong" }, 502),
    );

    expect(outcome).toEqual({
      kind: "error",
      message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
    });
  });

  it("returns an error view when the body fails schema validation", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({ not: "valid" }, 200),
    );

    expect(outcome).toEqual({
      kind: "error",
      message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
    });
  });

  it("returns a noPrevious view when previous/diff are both null", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse({
        current: SAMPLE_COMPARISON.current,
        previous: null,
        diff: null,
        warnings: ["比較できる過去履歴がまだありません。"],
      }),
    );

    expect(outcome).toEqual({
      kind: "noPrevious",
      message: HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE,
    });
  });

  it("returns a success view with the parsed comparison when previous/diff are present", async () => {
    const outcome = await resolveHistoryComparisonFetchOutcome(
      jsonComparisonResponse(SAMPLE_COMPARISON),
    );

    expect(outcome.kind).toBe("success");
    if (outcome.kind === "success") {
      expect(outcome.comparison.diff.visibilityScore.delta).toBe(5);
    }
  });
});

describe("formatSignedDelta", () => {
  it("formats a positive delta with a leading +", () => {
    expect(formatSignedDelta(5)).toBe("+5");
  });

  it("formats a negative delta as-is (already has a minus sign)", () => {
    expect(formatSignedDelta(-7)).toBe("-7");
  });

  it("formats a zero delta as ±0", () => {
    expect(formatSignedDelta(0)).toBe("±0");
  });
});

describe("formatComparisonVisibilityScoreLabel", () => {
  it("formats previous → current（delta）", () => {
    expect(
      formatComparisonVisibilityScoreLabel({ current: 91, previous: 86, delta: 5 }),
    ).toBe("86 → 91（+5）");
  });

  it("formats a negative delta", () => {
    expect(
      formatComparisonVisibilityScoreLabel({ current: 84, previous: 91, delta: -7 }),
    ).toBe("91 → 84（-7）");
  });

  it("formats a zero delta", () => {
    expect(
      formatComparisonVisibilityScoreLabel({ current: 86, previous: 86, delta: 0 }),
    ).toBe("86 → 86（±0）");
  });

  it("returns null when current is missing", () => {
    expect(
      formatComparisonVisibilityScoreLabel({ current: null, previous: 86, delta: null }),
    ).toBeNull();
  });

  it("returns null when previous is missing", () => {
    expect(
      formatComparisonVisibilityScoreLabel({ current: 91, previous: null, delta: null }),
    ).toBeNull();
  });
});

describe("formatComparisonImprovementsLabel", () => {
  it("formats previous → current（delta）", () => {
    expect(
      formatComparisonImprovementsLabel({ currentCount: 4, previousCount: 3, delta: 1 }),
    ).toBe("3 → 4（+1）");
  });

  it("formats a negative delta", () => {
    expect(
      formatComparisonImprovementsLabel({ currentCount: 1, previousCount: 3, delta: -2 }),
    ).toBe("3 → 1（-2）");
  });
});

describe("cooccurrence comparison term labels", () => {
  it("formats a new term with its rank", () => {
    expect(formatCooccurrenceNewTermLabel({ term: "ChatGPT", rank: 3, score: 12 })).toBe(
      "ChatGPT（3位）",
    );
  });

  it("formats a removed term with its (previous) rank", () => {
    expect(formatCooccurrenceRemovedTermLabel({ term: "広告", rank: 7, score: 5 })).toBe(
      "広告（7位）",
    );
  });

  it("formats a changed term with rank and score movement", () => {
    const label = formatCooccurrenceChangedTermLabel({
      term: "SEO",
      currentRank: 2,
      previousRank: 5,
      rankDelta: -3,
      currentScore: 18,
      previousScore: 12,
      scoreDelta: 6,
    });

    expect(label).toBe("SEO（5位→2位、スコア12→18）");
  });
});

describe("limitComparisonTerms", () => {
  it("caps a list to the default display limit", () => {
    const terms = Array.from({ length: 11 }, (_, i) => `term${i}`);

    expect(limitComparisonTerms(terms)).toHaveLength(5);
  });

  it("respects a custom limit", () => {
    const terms = ["a", "b", "c"];

    expect(limitComparisonTerms(terms, 2)).toEqual(["a", "b"]);
  });

  it("returns the full list when it is shorter than the limit", () => {
    const terms = ["a", "b"];

    expect(limitComparisonTerms(terms)).toEqual(["a", "b"]);
  });
});
