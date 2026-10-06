import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ANALYSIS_RESULT_PREVIEW_NOTE,
  GEMINI_RERUN_BUTTON_LABEL,
  GEMINI_RERUN_CONFIRM_MESSAGE,
  GEMINI_RERUN_DISABLED_MESSAGE,
  GEMINI_RERUN_FORBIDDEN_MESSAGE,
  GEMINI_RERUN_GENERIC_ERROR_MESSAGE,
  GEMINI_RERUN_HELPER_TEXT,
  GEMINI_RERUN_INCOMPATIBLE_MESSAGE,
  GEMINI_RERUN_NOT_FOUND_MESSAGE,
  GEMINI_RERUN_PENDING_TEXT,
  GEMINI_RERUN_SUCCESS_MESSAGE,
  HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
  HISTORY_COMPARISON_NOT_FOUND_MESSAGE,
  HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE,
  HISTORY_DELETE_ERROR_MESSAGE,
  HISTORY_DELETE_NOT_FOUND_MESSAGE,
  HISTORY_DETAIL_GENERIC_ERROR_MESSAGE,
  HISTORY_DETAIL_INCOMPATIBLE_MESSAGE,
  HISTORY_DETAIL_NOT_FOUND_MESSAGE,
  HISTORY_DETAIL_OFFICIAL_NOTE,
  HISTORY_DISABLED_MESSAGE,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_FORBIDDEN_MESSAGE,
  HISTORY_GENERIC_ERROR_MESSAGE,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  HISTORY_LIST_LINK_TEXT,
  HISTORY_LIST_PATH,
  HISTORY_PAGE_TITLE,
  HISTORY_SEARCH_NO_RESULTS_TEXT,
  HISTORY_SEARCH_PLACEHOLDER,
  HISTORY_SORT_DEFAULT_ORDER,
  HISTORY_SORT_NEWEST_LABEL,
  HISTORY_SORT_OLDEST_LABEL,
  POST_ANALYZE_HISTORY_CARD_HEADING,
  POST_ANALYZE_HISTORY_LINK_HELPER_TEXT,
  POST_ANALYZE_HISTORY_LINK_TEXT,
  REPORT_COMPARISON_UNAVAILABLE_MESSAGE,
  REPORT_DETAIL_UNAVAILABLE_MESSAGE,
  REPORT_LINK_TEXT,
  REPORT_PRINT_BUTTON_LABEL,
  buildDomainSearchVariants,
  buildHistoryDetailPath,
  buildHistoryReportPath,
  extractHostname,
  formatAnalysisRunDetailBasicInfo,
  formatAnalysisRunListItem,
  formatComparisonImprovementsLabel,
  formatComparisonVisibilityScoreLabel,
  formatCooccurrenceChangedTermLabel,
  formatCooccurrenceNewTermLabel,
  formatCooccurrenceRemovedTermLabel,
  formatHistoryCountLabel,
  formatModeSummaryBadges,
  formatSignedDelta,
  formatSourceSummary,
  filterAnalysisRunListItems,
  getStatusLabel,
  limitComparisonTerms,
  limitReportCooccurrenceTerms,
  printReport,
  getImportantToggleLabel,
  resolveDeleteAnalysisRunOutcome,
  resolveGeminiRerunOutcome,
  resolveHistoryComparisonFetchOutcome,
  resolveHistoryDetailFetchOutcome,
  resolveHistoryFetchOutcome,
  resolvePostAnalyzeHistoryLink,
  resolveReportComparisonMessage,
  resolveReportDetailMessage,
  resolveSetAnalysisRunImportantOutcome,
  sortAnalysisRunListItems,
  HISTORY_IMPORTANT_BADGE_LABEL,
  HISTORY_IMPORTANT_ERROR_MESSAGE,
  HISTORY_IMPORTANT_MARK_LABEL,
  HISTORY_IMPORTANT_NOT_FOUND_MESSAGE,
  HISTORY_IMPORTANT_UNMARK_LABEL,
} from "./analysis-history";
import type {
  AnalysisRunComparisonResponse,
  AnalysisRunDetailResponse,
  AnalysisRunDetailViewState,
  AnalysisRunListItem,
  HistoryComparisonViewState,
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

  it("falls back to the first sourceUrls entry's hostname for canonicalDomainLabel when canonicalDomain is absent (the realistic case — see fix/history-domain-search)", () => {
    const display = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
      sourceUrls: ["https://www.cybozu.co.jp/", "https://example.com/"],
    });

    expect(display.canonicalDomainLabel).toBe("www.cybozu.co.jp");
  });

  it("prefers canonicalDomain over sourceUrls when both are present", () => {
    const display = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
      canonicalDomain: "cybozu.co.jp",
      sourceUrls: ["https://example.com/"],
    });

    expect(display.canonicalDomainLabel).toBe("cybozu.co.jp");
  });

  it("omits canonicalDomainLabel when neither canonicalDomain nor sourceUrls is available", () => {
    const display = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
    });

    expect(display.canonicalDomainLabel).toBeUndefined();
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

  it("includes modeBadges derived from the item's modeSummary", () => {
    const display = formatAnalysisRunListItem({
      ...SAMPLE_ITEM,
      modeSummary: {
        aiOverview: "live",
        chatgpt: "real",
        claude: "off",
        gemini: "unavailable",
        commonCrawl: "real",
      },
    });

    expect(display.modeBadges).toEqual([
      { label: "AI Overview", value: "実測(Live)" },
      { label: "ChatGPT", value: "ON" },
      { label: "Claude", value: "OFF" },
      { label: "Gemini", value: "未取得" },
      { label: "Common Crawl", value: "ON" },
    ]);
  });

  it("falls back to all-unknown modeBadges when modeSummary is absent (old history)", () => {
    const display = formatAnalysisRunListItem({
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
    });

    expect(display.modeBadges).toEqual([
      { label: "AI Overview", value: "不明" },
      { label: "ChatGPT", value: "不明" },
      { label: "Claude", value: "不明" },
      { label: "Gemini", value: "不明" },
      { label: "Common Crawl", value: "不明" },
    ]);
  });
});

describe("formatModeSummaryBadges", () => {
  it("maps every known aiOverview value to its display label", () => {
    const values = ["mock", "sandbox", "live", "off", "unavailable", "unknown"] as const;
    const labels = values.map(
      (aiOverview) =>
        formatModeSummaryBadges({
          aiOverview,
          chatgpt: "unknown",
          claude: "unknown",
          gemini: "unknown",
          commonCrawl: "unknown",
        })[0].value,
    );

    expect(labels).toEqual(["mock", "実測(Sandbox)", "実測(Live)", "OFF", "未取得", "不明"]);
  });

  it("maps every known simple-provider value to its display label", () => {
    const values = ["real", "off", "unavailable", "unknown"] as const;
    const labels = values.map(
      (chatgpt) =>
        formatModeSummaryBadges({
          aiOverview: "unknown",
          chatgpt,
          claude: "unknown",
          gemini: "unknown",
          commonCrawl: "unknown",
        })[1].value,
    );

    expect(labels).toEqual(["ON", "OFF", "未取得", "不明"]);
  });

  it("shows an unrecognized value as-is rather than dropping it", () => {
    const badges = formatModeSummaryBadges({
      aiOverview: "unknown",
      chatgpt: "some-future-value",
      claude: "unknown",
      gemini: "unknown",
      commonCrawl: "unknown",
    });

    expect(badges[1]).toEqual({ label: "ChatGPT", value: "some-future-value" });
  });
});

describe("history list search/sort copy (improve/history-list-search-and-sort)", () => {
  it("matches the task's specified placeholder/no-results/sort labels", () => {
    expect(HISTORY_SEARCH_PLACEHOLDER).toBe("ブランド名で履歴を検索");
    expect(HISTORY_SEARCH_NO_RESULTS_TEXT).toBe("条件に一致する履歴がありません。");
    expect(HISTORY_SORT_NEWEST_LABEL).toBe("新しい順");
    expect(HISTORY_SORT_OLDEST_LABEL).toBe("古い順");
    expect(HISTORY_SORT_DEFAULT_ORDER).toBe("newest");
  });
});

describe("extractHostname", () => {
  it("extracts the hostname from a well-formed URL", () => {
    expect(extractHostname("https://www.cybozu.co.jp/")).toBe("www.cybozu.co.jp");
    expect(extractHostname("https://cybozu.co.jp/about/company")).toBe("cybozu.co.jp");
    expect(extractHostname("http://cybozu.co.jp")).toBe("cybozu.co.jp");
  });

  it("tolerates a bare domain with no scheme", () => {
    expect(extractHostname("cybozu.co.jp")).toBe("cybozu.co.jp");
    expect(extractHostname("www.cybozu.co.jp")).toBe("www.cybozu.co.jp");
  });

  it("returns null for a string that isn't a URL or domain at all", () => {
    expect(extractHostname("not a url at all")).toBeNull();
    expect(extractHostname("")).toBeNull();
  });
});

describe("buildDomainSearchVariants", () => {
  it("includes the bare domain, www.-prefixed domain, and both under http(s) with a trailing slash", () => {
    const variants = buildDomainSearchVariants("https://www.cybozu.co.jp/");

    expect(variants).toContain("cybozu.co.jp");
    expect(variants).toContain("www.cybozu.co.jp");
    expect(variants).toContain("https://cybozu.co.jp/");
    expect(variants).toContain("https://www.cybozu.co.jp/");
    expect(variants).toContain("http://cybozu.co.jp/");
    expect(variants).toContain("http://www.cybozu.co.jp/");
  });

  it("produces the same variant set regardless of which form was stored", () => {
    const fromBare = new Set(buildDomainSearchVariants("https://cybozu.co.jp/"));
    const fromWww = new Set(buildDomainSearchVariants("https://www.cybozu.co.jp/"));

    expect(fromBare).toEqual(fromWww);
  });

  it("lowercases everything", () => {
    expect(buildDomainSearchVariants("https://WWW.Cybozu.Co.JP/")).toContain("www.cybozu.co.jp");
  });

  it("falls back to just the lowercased input when it doesn't parse as a URL/hostname", () => {
    expect(buildDomainSearchVariants("Not A URL")).toEqual(["not a url"]);
  });
});

describe("filterAnalysisRunListItems", () => {
  function item(overrides: Partial<AnalysisRunListItem> = {}): AnalysisRunListItem {
    return {
      id: "id",
      brandName: "サイボウズ",
      status: "completed",
      ...overrides,
    };
  }

  it("returns every item when the query is blank", () => {
    const items = [item({ id: "a" }), item({ id: "b" })];
    expect(filterAnalysisRunListItems(items, "")).toEqual(items);
    expect(filterAnalysisRunListItems(items, "   ")).toEqual(items);
  });

  it("matches brandName case-insensitively", () => {
    const items = [item({ id: "a", brandName: "Cybozu" }), item({ id: "b", brandName: "freee" })];
    expect(filterAnalysisRunListItems(items, "cybozu")).toEqual([items[0]]);
  });

  it("matches canonicalDomain (stand-in for 'analyzed URL' on this list shape)", () => {
    const items = [
      item({ id: "a", brandName: "サイボウズ", canonicalDomain: "cybozu.co.jp" }),
      item({ id: "b", brandName: "freee" }),
    ];
    expect(filterAnalysisRunListItems(items, "cybozu.co.jp")).toEqual([items[0]]);
  });

  describe("domain search via sourceUrls (fix/history-domain-search)", () => {
    // canonicalDomain is never actually populated by the backend's
    // save path today — sourceUrls (the raw input URL strings) is the
    // realistic case this bug report was about.
    function cybozuItem(): AnalysisRunListItem {
      return item({
        id: "cybozu",
        brandName: "サイボウズ",
        sourceUrls: ["https://www.cybozu.co.jp/"],
      });
    }

    it("matches a bare domain query", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "cybozu.co.jp")).toEqual([cybozuItem()]);
    });

    it("matches a bare substring query", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "cybozu")).toEqual([cybozuItem()]);
    });

    it("matches with a www. prefix even though the stored URL already has one", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "www.cybozu.co.jp")).toEqual([
        cybozuItem(),
      ]);
    });

    it("matches without a www. prefix even though the stored URL has one", () => {
      // The reverse of the above — the stored sourceUrls entry has
      // "www.", but a query without it must still hit, since
      // buildDomainSearchVariants() synthesizes both forms.
      expect(filterAnalysisRunListItems([cybozuItem()], "cybozu.co.jp")).toEqual([cybozuItem()]);
    });

    it("matches a full https:// URL with trailing slash, bare domain", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "https://cybozu.co.jp/")).toEqual([
        cybozuItem(),
      ]);
    });

    it("matches a full https:// URL with trailing slash, www. domain", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "https://www.cybozu.co.jp/")).toEqual([
        cybozuItem(),
      ]);
    });

    it("is case-insensitive", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "CYBOZU.CO.JP")).toEqual([cybozuItem()]);
    });

    it("does not match an unrelated domain", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "freee.co.jp")).toEqual([]);
    });

    it("still matches brandName when sourceUrls is present (brandName search is unaffected)", () => {
      expect(filterAnalysisRunListItems([cybozuItem()], "サイボウズ")).toEqual([cybozuItem()]);
    });

    it("searches every entry when sourceUrls has more than one URL", () => {
      const multi = item({
        id: "multi",
        sourceUrls: ["https://example.com/", "https://cybozu.co.jp/about"],
      });
      expect(filterAnalysisRunListItems([multi], "cybozu.co.jp")).toEqual([multi]);
    });

    it("never throws when sourceUrls is undefined (older saved history)", () => {
      expect(filterAnalysisRunListItems([item({ id: "old" })], "cybozu.co.jp")).toEqual([]);
      expect(
        filterAnalysisRunListItems([item({ id: "old", sourceUrls: undefined })], "cybozu"),
      ).toEqual([]);
    });

    it("never throws for a sourceUrls entry that isn't a valid URL", () => {
      const malformed = item({ id: "malformed", sourceUrls: ["not a url at all"] });
      expect(() => filterAnalysisRunListItems([malformed], "cybozu")).not.toThrow();
      expect(filterAnalysisRunListItems([malformed], "not a url")).toEqual([malformed]);
    });
  });

  it("matches the startedAt/createdAt timestamp text", () => {
    const items = [
      item({ id: "a", startedAt: "2026-09-09T00:00:00+09:00" }),
      item({ id: "b", startedAt: "2026-01-01T00:00:00+09:00" }),
    ];
    expect(filterAnalysisRunListItems(items, "2026-09-09")).toEqual([items[0]]);
  });

  it("returns an empty array when nothing matches", () => {
    expect(filterAnalysisRunListItems([item()], "存在しないブランド")).toEqual([]);
  });

  it("never throws on an item missing every optional field", () => {
    expect(filterAnalysisRunListItems([item()], "サイボウズ")).toEqual([item()]);
  });
});

describe("sortAnalysisRunListItems", () => {
  function item(id: string, startedAt?: string): AnalysisRunListItem {
    return { id, brandName: "Acme", status: "completed", startedAt };
  }

  it("sorts newest first by default order", () => {
    const items = [
      item("old", "2026-01-01T00:00:00+09:00"),
      item("new", "2026-09-09T00:00:00+09:00"),
    ];
    expect(sortAnalysisRunListItems(items, "newest").map((i) => i.id)).toEqual(["new", "old"]);
  });

  it("sorts oldest first when asked", () => {
    const items = [
      item("new", "2026-09-09T00:00:00+09:00"),
      item("old", "2026-01-01T00:00:00+09:00"),
    ];
    expect(sortAnalysisRunListItems(items, "oldest").map((i) => i.id)).toEqual(["old", "new"]);
  });

  it("falls back to createdAt when startedAt is absent", () => {
    const items = [
      { id: "old", brandName: "Acme", status: "completed", createdAt: "2026-01-01T00:00:00+09:00" },
      { id: "new", brandName: "Acme", status: "completed", createdAt: "2026-09-09T00:00:00+09:00" },
    ];
    expect(sortAnalysisRunListItems(items, "newest").map((i) => i.id)).toEqual(["new", "old"]);
  });

  it("sorts an item with no timestamp at all to the end in both orders", () => {
    const items = [
      item("no-timestamp"),
      item("has-timestamp", "2026-01-01T00:00:00+09:00"),
    ];
    expect(sortAnalysisRunListItems(items, "newest").map((i) => i.id)).toEqual([
      "has-timestamp",
      "no-timestamp",
    ]);
    expect(sortAnalysisRunListItems(items, "oldest").map((i) => i.id)).toEqual([
      "has-timestamp",
      "no-timestamp",
    ]);
  });

  it("never mutates the input array", () => {
    const items = [item("a", "2026-01-01T00:00:00+09:00"), item("b", "2026-09-09T00:00:00+09:00")];
    const original = [...items];
    sortAnalysisRunListItems(items, "newest");
    expect(items).toEqual(original);
  });
});

describe("formatHistoryCountLabel", () => {
  it("shows a single count when nothing is filtered out", () => {
    expect(formatHistoryCountLabel(12, 12)).toBe("12件の履歴");
  });

  it("shows both totals once a search narrows the list", () => {
    expect(formatHistoryCountLabel(12, 3)).toBe("12件中 3件を表示");
  });

  it("handles zero matches", () => {
    expect(formatHistoryCountLabel(12, 0)).toBe("12件中 0件を表示");
  });

  it("handles a zero-item history", () => {
    expect(formatHistoryCountLabel(0, 0)).toBe("0件の履歴");
  });
});

describe("resolveDeleteAnalysisRunOutcome", () => {
  it("returns success for a 200 response", async () => {
    const outcome = await resolveDeleteAnalysisRunOutcome(jsonResponse({ deleted: true }, 200));

    expect(outcome).toEqual({ success: true });
  });

  it("returns a forbidden message for a 403 response", async () => {
    const outcome = await resolveDeleteAnalysisRunOutcome(
      jsonResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_FORBIDDEN_MESSAGE });
  });

  it("returns a not-found message for a 404 response", async () => {
    const outcome = await resolveDeleteAnalysisRunOutcome(
      jsonResponse({ error: "analysis run not found" }, 404),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_DELETE_NOT_FOUND_MESSAGE });
  });

  it("returns a generic error message when the response is null (network failure)", async () => {
    const outcome = await resolveDeleteAnalysisRunOutcome(null);

    expect(outcome).toEqual({ success: false, message: HISTORY_DELETE_ERROR_MESSAGE });
  });

  it("returns a generic error message for any other failure status", async () => {
    const outcome = await resolveDeleteAnalysisRunOutcome(
      jsonResponse({ error: "something went wrong" }, 502),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_DELETE_ERROR_MESSAGE });
  });
});

describe("getImportantToggleLabel (feature/history-important-flag)", () => {
  it("returns the mark label when currently not important", () => {
    expect(getImportantToggleLabel(false)).toBe(HISTORY_IMPORTANT_MARK_LABEL);
  });

  it("returns the unmark label when currently important", () => {
    expect(getImportantToggleLabel(true)).toBe(HISTORY_IMPORTANT_UNMARK_LABEL);
  });
});

describe("HISTORY_IMPORTANT_BADGE_LABEL", () => {
  it("is the Japanese badge text shown when a run is marked important", () => {
    expect(HISTORY_IMPORTANT_BADGE_LABEL).toBe("重要");
  });
});

describe("resolveSetAnalysisRunImportantOutcome (feature/history-important-flag)", () => {
  it("returns success with the updated isImportant for a 200 response", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ analysisRunId: SAMPLE_ITEM.id, isImportant: true }, 200),
    );

    expect(outcome).toEqual({ success: true, isImportant: true });
  });

  it("returns success with isImportant: false when unmarking", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ analysisRunId: SAMPLE_ITEM.id, isImportant: false }, 200),
    );

    expect(outcome).toEqual({ success: true, isImportant: false });
  });

  it("returns a forbidden message for a 403 response", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_FORBIDDEN_MESSAGE });
  });

  it("returns a not-found message for a 404 response", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ error: "analysis run not found" }, 404),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_IMPORTANT_NOT_FOUND_MESSAGE });
  });

  it("returns a generic error message when the response is null (network failure)", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(null);

    expect(outcome).toEqual({ success: false, message: HISTORY_IMPORTANT_ERROR_MESSAGE });
  });

  it("returns a generic error message for any other failure status", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ error: "something went wrong" }, 502),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_IMPORTANT_ERROR_MESSAGE });
  });

  it("returns a generic error message when the success body fails schema validation", async () => {
    const outcome = await resolveSetAnalysisRunImportantOutcome(
      jsonResponse({ analysisRunId: SAMPLE_ITEM.id }, 200),
    );

    expect(outcome).toEqual({ success: false, message: HISTORY_IMPORTANT_ERROR_MESSAGE });
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

describe("Gemini rerun UI copy", () => {
  it("matches the task's specified button/helper/confirm/pending/success text", () => {
    expect(GEMINI_RERUN_BUTTON_LABEL).toBe("Geminiだけ再実行");
    expect(GEMINI_RERUN_HELPER_TEXT).toBe(
      "Geminiの回答のみを再取得します。他のAI観測やAI Overviewは再実行しません。",
    );
    expect(GEMINI_RERUN_CONFIRM_MESSAGE).toBe(
      "Geminiの回答のみを再取得します。Gemini APIを1回使用します。実行しますか？",
    );
    expect(GEMINI_RERUN_PENDING_TEXT).toBe("Gemini再実行中...");
    expect(GEMINI_RERUN_SUCCESS_MESSAGE).toContain("完了");
  });
});

describe("resolveGeminiRerunOutcome", () => {
  const SAMPLE_RERUN_RESPONSE = {
    updated: true,
    analysisRunId: SAMPLE_DETAIL.id,
    result: buildDummyAnalysis("サイボウズ") as unknown as Record<string, unknown>,
  };

  it("returns a disabled failure when the response is 503", async () => {
    const outcome = await resolveGeminiRerunOutcome(
      jsonDetailResponse({ error: "analysis history read API is not enabled" }, 503),
    );

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_DISABLED_MESSAGE });
  });

  it("returns a forbidden failure when the response is 403", async () => {
    const outcome = await resolveGeminiRerunOutcome(
      jsonDetailResponse({ error: "analysis history read access denied" }, 403),
    );

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_FORBIDDEN_MESSAGE });
  });

  it("returns a notFound-style failure when the response is 404", async () => {
    const outcome = await resolveGeminiRerunOutcome(
      jsonDetailResponse({ error: "analysis run not found" }, 404),
    );

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_NOT_FOUND_MESSAGE });
  });

  it("forwards the backend's own reason text for a 502 (Gemini call failed/disabled)", async () => {
    const outcome = await resolveGeminiRerunOutcome(
      jsonDetailResponse({ error: "Gemini request limit must be 1." }, 502),
    );

    expect(outcome).toEqual({ success: false, message: "Gemini request limit must be 1." });
  });

  it("falls back to a generic message when a 502 body has no usable error text", async () => {
    const outcome = await resolveGeminiRerunOutcome(jsonDetailResponse({}, 502));

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_GENERIC_ERROR_MESSAGE });
  });

  it("returns a generic failure when the network request itself failed (response is null)", async () => {
    const outcome = await resolveGeminiRerunOutcome(null);

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_GENERIC_ERROR_MESSAGE });
  });

  it("returns a generic failure for a non-403/404/502/503 failure status", async () => {
    const outcome = await resolveGeminiRerunOutcome(jsonDetailResponse({ error: "boom" }, 500));

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_GENERIC_ERROR_MESSAGE });
  });

  it("returns a generic failure when the envelope fails schema validation", async () => {
    const outcome = await resolveGeminiRerunOutcome(jsonDetailResponse({ not: "valid" }, 200));

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_GENERIC_ERROR_MESSAGE });
  });

  it("returns an incompatible failure when result doesn't match the current AnalysisResult shape", async () => {
    const outcome = await resolveGeminiRerunOutcome(
      jsonDetailResponse({ ...SAMPLE_RERUN_RESPONSE, result: { some: "old shape" } }, 200),
    );

    expect(outcome).toEqual({ success: false, message: GEMINI_RERUN_INCOMPATIBLE_MESSAGE });
  });

  it("returns success with the parsed result when everything validates", async () => {
    const outcome = await resolveGeminiRerunOutcome(jsonDetailResponse(SAMPLE_RERUN_RESPONSE, 200));

    expect(outcome.success).toBe(true);
    if (outcome.success) {
      expect(outcome.result.brandName).toBe("サイボウズ");
    }
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

describe("history-centered analysis flow copy (improve/history-centered-analysis-flow)", () => {
  it("names the history detail screen as the official place to check results/report/rerun", () => {
    expect(POST_ANALYZE_HISTORY_CARD_HEADING).toContain("履歴詳細");
    expect(POST_ANALYZE_HISTORY_LINK_HELPER_TEXT).toContain("レポート表示");
    expect(POST_ANALYZE_HISTORY_LINK_HELPER_TEXT).toContain("再実行");
    expect(POST_ANALYZE_HISTORY_LINK_TEXT).toContain("履歴詳細");
  });

  it("frames the analysis result screen as a preview", () => {
    expect(ANALYSIS_RESULT_PREVIEW_NOTE).toContain("プレビュー");
    expect(ANALYSIS_RESULT_PREVIEW_NOTE).toContain("履歴詳細");
  });

  it("frames the history detail screen as the official confirmation screen", () => {
    expect(HISTORY_DETAIL_OFFICIAL_NOTE).toContain("保存済み");
    expect(HISTORY_DETAIL_OFFICIAL_NOTE).toContain("レポート表示");
    expect(HISTORY_DETAIL_OFFICIAL_NOTE).toContain("再実行");
  });

  it("points the history-list link at /history", () => {
    expect(HISTORY_LIST_PATH).toBe("/history");
    expect(HISTORY_LIST_LINK_TEXT).toContain("履歴一覧");
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

// --- Report page (docs/26_report_output_design.md) ---

describe("REPORT_LINK_TEXT", () => {
  it("is the Japanese link text shown on /history/[id]", () => {
    expect(REPORT_LINK_TEXT).toBe("レポート表示");
  });
});

describe("buildHistoryReportPath", () => {
  it("builds a /history/{id}/report path", () => {
    expect(buildHistoryReportPath("11111111-1111-1111-1111-111111111111")).toBe(
      "/history/11111111-1111-1111-1111-111111111111/report",
    );
  });

  it("URL-encodes the id", () => {
    expect(buildHistoryReportPath("has space")).toBe("/history/has%20space/report");
  });
});

describe("resolveReportDetailMessage", () => {
  type NonTerminalDetailView = Exclude<
    AnalysisRunDetailViewState,
    { kind: "loading" } | { kind: "success" }
  >;

  it("passes through the forbidden message as-is (403)", () => {
    const view: NonTerminalDetailView = { kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE };
    expect(resolveReportDetailMessage(view)).toBe(HISTORY_FORBIDDEN_MESSAGE);
  });

  it("passes through the disabled message as-is (503)", () => {
    const view: NonTerminalDetailView = {
      kind: "disabled",
      message: HISTORY_DISABLED_MESSAGE,
      detail: "some detail",
    };
    expect(resolveReportDetailMessage(view)).toBe(HISTORY_DISABLED_MESSAGE);
  });

  it("falls back to the generic report-unavailable message for notFound", () => {
    const view: NonTerminalDetailView = {
      kind: "notFound",
      message: HISTORY_DETAIL_NOT_FOUND_MESSAGE,
    };
    expect(resolveReportDetailMessage(view)).toBe(REPORT_DETAIL_UNAVAILABLE_MESSAGE);
  });

  it("falls back to the generic report-unavailable message for incompatible", () => {
    const view: NonTerminalDetailView = {
      kind: "incompatible",
      message: HISTORY_DETAIL_INCOMPATIBLE_MESSAGE,
    };
    expect(resolveReportDetailMessage(view)).toBe(REPORT_DETAIL_UNAVAILABLE_MESSAGE);
  });

  it("falls back to the generic report-unavailable message for a generic error", () => {
    const view: NonTerminalDetailView = {
      kind: "error",
      message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE,
    };
    expect(resolveReportDetailMessage(view)).toBe(REPORT_DETAIL_UNAVAILABLE_MESSAGE);
  });
});

describe("resolveReportComparisonMessage", () => {
  type NonTerminalComparisonView = Exclude<
    HistoryComparisonViewState,
    { kind: "loading" } | { kind: "success" }
  >;

  it("passes through the forbidden message as-is (403)", () => {
    const view: NonTerminalComparisonView = {
      kind: "forbidden",
      message: HISTORY_FORBIDDEN_MESSAGE,
    };
    expect(resolveReportComparisonMessage(view)).toBe(HISTORY_FORBIDDEN_MESSAGE);
  });

  it("passes through the disabled message as-is (503)", () => {
    const view: NonTerminalComparisonView = {
      kind: "disabled",
      message: HISTORY_DISABLED_MESSAGE,
    };
    expect(resolveReportComparisonMessage(view)).toBe(HISTORY_DISABLED_MESSAGE);
  });

  it("passes through the no-previous-history message as-is", () => {
    const view: NonTerminalComparisonView = {
      kind: "noPrevious",
      message: HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE,
    };
    expect(resolveReportComparisonMessage(view)).toBe(HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE);
  });

  it("falls back to the report-specific comparison-unavailable message for notFound", () => {
    const view: NonTerminalComparisonView = {
      kind: "notFound",
      message: HISTORY_COMPARISON_NOT_FOUND_MESSAGE,
    };
    expect(resolveReportComparisonMessage(view)).toBe(REPORT_COMPARISON_UNAVAILABLE_MESSAGE);
  });

  it("falls back to the report-specific comparison-unavailable message for a generic error", () => {
    const view: NonTerminalComparisonView = {
      kind: "error",
      message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE,
    };
    expect(resolveReportComparisonMessage(view)).toBe(REPORT_COMPARISON_UNAVAILABLE_MESSAGE);
  });
});

describe("limitReportCooccurrenceTerms", () => {
  it("caps to the default display limit of 10", () => {
    const terms = Array.from({ length: 15 }, (_, i) => ({
      keyword: `term${i}`,
      count: i,
      trend: "flat" as const,
    }));

    expect(limitReportCooccurrenceTerms(terms)).toHaveLength(10);
  });

  it("respects a custom limit", () => {
    const terms = [
      { keyword: "a", count: 3, trend: "up" as const },
      { keyword: "b", count: 2, trend: "flat" as const },
      { keyword: "c", count: 1, trend: "down" as const },
    ];

    expect(limitReportCooccurrenceTerms(terms, 2)).toEqual([terms[0], terms[1]]);
  });

  it("returns the full list when it is shorter than the limit", () => {
    const terms = [{ keyword: "a", count: 1, trend: "flat" as const }];

    expect(limitReportCooccurrenceTerms(terms)).toEqual(terms);
  });
});

describe("REPORT_PRINT_BUTTON_LABEL", () => {
  it("is the Japanese print/PDF-save button label", () => {
    expect(REPORT_PRINT_BUTTON_LABEL).toBe("PDF保存 / 印刷");
  });
});

describe("printReport", () => {
  // This project's vitest run doesn't use a jsdom environment (no
  // `window` global exists by default in these tests, same as the
  // rest of this file), so `window.print` is stubbed via vi.stubGlobal
  // rather than assumed to already exist.
  let printSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    printSpy = vi.fn();
    vi.stubGlobal("window", { print: printSpy });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("calls window.print()", () => {
    printReport();
    expect(printSpy).toHaveBeenCalledTimes(1);
  });
});
