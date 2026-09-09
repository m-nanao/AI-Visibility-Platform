import { describe, expect, it } from "vitest";
import {
  HISTORY_DISABLED_MESSAGE,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_GENERIC_ERROR_MESSAGE,
  HISTORY_PAGE_TITLE,
  formatAnalysisRunListItem,
  formatSourceSummary,
  getStatusLabel,
  resolveHistoryFetchOutcome,
} from "./analysis-history";
import type { AnalysisRunListItem } from "./analysis-history";

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

  it("returns an error view when the network request itself failed (response is null)", async () => {
    const outcome = await resolveHistoryFetchOutcome(null);

    expect(outcome).toEqual({ kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE });
  });

  it("returns an error view for a non-503 failure status", async () => {
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
