import { describe, expect, it } from "vitest";
import {
  getAiOverviewProviderStatusDisplay,
  getCooccurrenceUnavailableMessage,
  getSectionStatusSummary,
  getUrlFetchSummary,
} from "./meta-label";
import { buildDummyAnalysis } from "./dummy-data";
import type { AnalysisMeta } from "./types";

function baseMeta(): AnalysisMeta {
  return buildDummyAnalysis("OpenAI").meta;
}

describe("getSectionStatusSummary", () => {
  it("reports all-mock as the dummy-data summary", () => {
    expect(getSectionStatusSummary(baseMeta())).toBe("すべて開発用データ（ダミー）");
  });

  it("reports the co-occurrence-only-real summary", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: { ...baseMeta().sections, cooccurrenceRanking: "real" },
    };

    expect(getSectionStatusSummary(meta)).toBe(
      "共起語のみ実計算、その他は開発用データ",
    );
  });

  it("reports an unavailable co-occurrence section distinctly from mock", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: { ...baseMeta().sections, cooccurrenceRanking: "unavailable" },
    };

    const summary = getSectionStatusSummary(meta);
    expect(summary).toContain("共起語は取得失敗のため計算不能");
    expect(summary).toContain("その他は開発用データ");
  });

  it("reports all-real as fully computed", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: {
        summary: "real",
        cooccurrenceRanking: "real",
        contextAnalysis: "real",
        aiOverviewComparison: "real",
        improvements: "real",
      },
    };

    expect(getSectionStatusSummary(meta)).toBe("すべて実計算");
  });

  it("calls out a DataForSEO Sandbox aiOverviewComparison separately instead of lumping it into 実計算", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: {
        summary: "real",
        cooccurrenceRanking: "real",
        contextAnalysis: "real",
        aiOverviewComparison: "real",
        improvements: "real",
      },
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "real",
        reason: "DataForSEO Sandbox AI Mode request succeeded.",
      },
    };

    const summary = getSectionStatusSummary(meta);
    expect(summary).not.toBe("すべて実計算");
    expect(summary).toContain("AI Overview比較はDataForSEO Sandbox");
    expect(summary).not.toContain("AI Overview比較のみ実計算");
  });

  it("still reports the co-occurrence-only-real summary when aiOverviewComparison is mock", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: { ...baseMeta().sections, cooccurrenceRanking: "real" },
      aiOverviewProvider: {
        mode: "mock",
        status: "mock",
        reason: "Using mock AI Overview data for development.",
      },
    };

    expect(getSectionStatusSummary(meta)).toBe(
      "共起語のみ実計算、その他は開発用データ",
    );
  });
});

describe("getAiOverviewProviderStatusDisplay", () => {
  it("returns null when meta.aiOverviewProvider is absent (e.g. the client-side dummy fallback)", () => {
    expect(getAiOverviewProviderStatusDisplay(baseMeta())).toBeNull();
  });

  it("describes mock mode as development data", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "mock",
        status: "mock",
        reason: "Using mock AI Overview data for development.",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("開発用データ");
    expect(display?.tone).toBe("neutral");
    expect(display?.caution).toBeUndefined();
  });

  it("describes off mode as disabled", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "off",
        status: "unavailable",
        reason: "AI Overview comparison is disabled (AI_OVERVIEW_PROVIDER_MODE=off).",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("無効");
    expect(display?.tone).toBe("neutral");
  });

  it("describes a successful DataForSEO Sandbox result with a caution that it isn't production data", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "real",
        reason: "DataForSEO Sandbox AI Mode request succeeded.",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO Sandbox");
    expect(display?.tone).toBe("caution");
    expect(display?.caution).toContain("本番");
  });

  it("describes a failed/unavailable DataForSEO attempt without exposing the raw reason", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "unavailable",
        reason: "DataForSEO credentials are not configured (DATAFORSEO_LOGIN/DATAFORSEO_PASSWORD).",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO 未取得");
    expect(display?.tone).toBe("neutral");
    expect(display?.description).not.toContain("DATAFORSEO_LOGIN");
  });
});

describe("getCooccurrenceUnavailableMessage", () => {
  it("returns null when cooccurrenceRanking is mock", () => {
    expect(getCooccurrenceUnavailableMessage(baseMeta())).toBeNull();
  });

  it("returns null when cooccurrenceRanking is real", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: { ...baseMeta().sections, cooccurrenceRanking: "real" },
    };
    expect(getCooccurrenceUnavailableMessage(meta)).toBeNull();
  });

  it("returns the user-facing message when cooccurrenceRanking is unavailable", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      sections: { ...baseMeta().sections, cooccurrenceRanking: "unavailable" },
    };

    expect(getCooccurrenceUnavailableMessage(meta)).toBe(
      "URLを取得できなかったため共起解析を実行できませんでした",
    );
  });
});

describe("getUrlFetchSummary", () => {
  it("returns null when there are no url fetch results", () => {
    expect(getUrlFetchSummary(baseMeta())).toBeNull();
  });

  it("notes that only the fetched pages were analyzed on partial success, without exposing raw error text", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [
        { url: "https://example.com/a", success: true },
        { url: "http://localhost/b", success: false, error: "resolves to a disallowed address: 127.0.0.1" },
      ],
    };

    const summary = getUrlFetchSummary(meta);
    expect(summary).toBe("URL取得: 1/2件成功（取得できたページのみで分析しています）");
    expect(summary).not.toContain("127.0.0.1");
  });

  it("reports a plain count when all urls succeed", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [
        { url: "https://example.com/a", success: true },
        { url: "https://example.com/b", success: true },
      ],
    };

    expect(getUrlFetchSummary(meta)).toBe("URL取得: 2/2件成功");
  });

  it("reports a plain count when all urls fail", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [
        { url: "http://localhost/a", success: false, error: "resolves to a disallowed address: 127.0.0.1" },
      ],
    };

    expect(getUrlFetchSummary(meta)).toBe("URL取得: 0/1件成功");
  });
});
