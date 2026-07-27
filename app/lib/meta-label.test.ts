import { describe, expect, it } from "vitest";
import {
  REFERENCE_CATEGORY_LABELS,
  getAiOverviewItemDetailDisplay,
  getAiOverviewProviderStatusDisplay,
  getCooccurrenceUnavailableMessage,
  getSectionStatusSummary,
  getUrlFetchSummary,
} from "./meta-label";
import { buildDummyAnalysis } from "./dummy-data";
import type { AIOverviewComparisonItem, AnalysisMeta } from "./types";

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

  it("calls out a DataForSEO Live aiOverviewComparison separately from both 実計算 and Sandbox", () => {
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
        reason: "DataForSEO Live AI Mode request succeeded.",
        environment: "live",
      },
    };

    const summary = getSectionStatusSummary(meta);
    expect(summary).not.toBe("すべて実計算");
    expect(summary).toContain("AI Overview比較はDataForSEO Live");
    expect(summary).not.toContain("DataForSEO Sandbox");
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

  it("describes environment=sandbox explicitly the same way as the mode/status fallback", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "real",
        reason: "DataForSEO Sandbox AI Mode request succeeded.",
        environment: "sandbox",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO Sandbox");
    expect(display?.tone).toBe("caution");
    expect(display?.caution).toContain("本番");
  });

  it("describes environment=live with a distinct label and a cost-risk caution", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "real",
        reason: "DataForSEO Live AI Mode request succeeded.",
        environment: "live",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO Live");
    expect(display?.tone).toBe("caution");
    expect(display?.label).not.toBe("DataForSEO Sandbox");
    expect(display?.caution).toContain("費用");
  });

  it("describes environment=unavailable as not fetched, even when it came from a rejected Live attempt", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "unavailable",
        reason: "DataForSEO Live API is disabled. Set all manual live confirmation gates to enable one manual request.",
        environment: "unavailable",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO 未取得");
    expect(display?.tone).toBe("neutral");
  });

  it("describes environment=off as disabled, mirroring the mode=off fallback", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "off",
        status: "unavailable",
        reason: "AI Overview comparison is disabled (AI_OVERVIEW_PROVIDER_MODE=off).",
        environment: "off",
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("無効");
  });

  it("falls back to inferring sandbox from mode/status when environment is absent (older-backend compatibility)", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      aiOverviewProvider: {
        mode: "dataforseo",
        status: "real",
        reason: "DataForSEO Sandbox AI Mode request succeeded.",
        // environment intentionally omitted.
      },
    };

    const display = getAiOverviewProviderStatusDisplay(meta);
    expect(display?.label).toBe("DataForSEO Sandbox");
  });
});

describe("getAiOverviewItemDetailDisplay", () => {
  function baseItem(): AIOverviewComparisonItem {
    return {
      platform: "Google AI Mode (DataForSEO Sandbox)",
      mentioned: true,
      rank: 1,
      summary: "Acme is a well-reviewed tool for teams.",
    };
  }

  it("reports no detail/references and an unjudged own-domain status for a plain (e.g. mock) item", () => {
    const display = getAiOverviewItemDetailDisplay(baseItem());

    expect(display.hasDetail).toBe(false);
    expect(display.detailText).toBeUndefined();
    expect(display.references).toEqual([]);
    expect(display.ownDomainStatus).toBe("unjudged");
  });

  it("reports hasDetail=true with the full text when fullSummary is present", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      fullSummary: "Acme is a well-reviewed tool for teams, used by hundreds of companies.",
    });

    expect(display.hasDetail).toBe(true);
    expect(display.detailText).toBe(
      "Acme is a well-reviewed tool for teams, used by hundreds of companies.",
    );
  });

  it("maps references to a display label, preferring domain over url over title", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      references: [
        { domain: "acme.example.com", url: "https://acme.example.com/about", title: "About Acme" },
        { url: "https://only-url.example.com" },
        { title: "Only A Title" },
      ],
    });

    expect(display.references).toEqual([
      { label: "acme.example.com", title: "About Acme", url: "https://acme.example.com/about" },
      { label: "https://only-url.example.com", title: undefined, url: "https://only-url.example.com" },
      { label: "Only A Title", title: "Only A Title", url: undefined },
    ]);
  });

  it("caps references at 10 even if the backend response somehow included more", () => {
    const references = Array.from({ length: 15 }, (_, i) => ({ domain: `example${i}.com` }));

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), references });

    expect(display.references).toHaveLength(10);
  });

  it("reports ownDomainStatus=included when ownDomainReferenced is true", () => {
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), ownDomainReferenced: true });
    expect(display.ownDomainStatus).toBe("included");
  });

  it("reports ownDomainStatus=not_included when ownDomainReferenced is false", () => {
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), ownDomainReferenced: false });
    expect(display.ownDomainStatus).toBe("not_included");
  });

  it("reports ownDomainStatus=unjudged when ownDomainReferenced is undefined", () => {
    const display = getAiOverviewItemDetailDisplay(baseItem());
    expect(display.ownDomainStatus).toBe("unjudged");
  });

  it("provides everything the card layout needs to render, for a full DataForSEO item (no RTL in this project — see meta-label.ts's role as the presentation-logic layer for AIOverviewComparisonSection.tsx)", () => {
    const item: AIOverviewComparisonItem = {
      ...baseItem(),
      platform: "Google AI Mode (DataForSEO Sandbox)",
      rank: 2,
      mentioned: true,
      summary: "Acme is a well-reviewed tool for teams.",
      fullSummary: "Acme is a well-reviewed tool for teams, used by hundreds of companies worldwide.",
      references: [
        { domain: "acme.example.com", url: "https://acme.example.com/about", title: "About Acme" },
      ],
      ownDomainReferenced: true,
    };

    // Fields the card renders directly (platform/rank/mentioned/summary).
    expect(item.platform).toBe("Google AI Mode (DataForSEO Sandbox)");
    expect(item.rank).toBe(2);
    expect(item.mentioned).toBe(true);
    expect(item.summary).toBe("Acme is a well-reviewed tool for teams.");

    // Fields the card renders via getAiOverviewItemDetailDisplay
    // (fullSummary detail toggle, references with url usable as href,
    // own-domain note).
    const display = getAiOverviewItemDetailDisplay(item);
    expect(display.hasDetail).toBe(true);
    expect(display.detailText).toBe(item.fullSummary);
    expect(display.references).toEqual([
      { label: "acme.example.com", title: "About Acme", url: "https://acme.example.com/about" },
    ]);
    expect(display.ownDomainStatus).toBe("included");
  });

  it("returns an empty references array (not undefined) when the item has no references, so the card's references block is safely skipped", () => {
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), rank: null, mentioned: false });

    expect(display.references).toEqual([]);
    expect(display.references.length).toBe(0);
  });

  it("maps each reference's category to its display label", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      references: [
        { domain: "acme.example.com", category: "official" },
        { domain: "ja.wikipedia.org", category: "wikipedia" },
        { domain: "note.com", category: "ugc" },
      ],
    });

    expect(display.references.map((r) => r.categoryLabel)).toEqual(["公式", "Wikipedia", "UGC・投稿サイト"]);
  });

  it("leaves categoryLabel undefined for a reference without a category (older backend response)", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      references: [{ domain: "acme.example.com" }],
    });

    expect(display.references[0].categoryLabel).toBeUndefined();
  });

  it("returns no referenceSummary when the item has no referenceSummary", () => {
    const display = getAiOverviewItemDetailDisplay(baseItem());
    expect(display.referenceSummary).toBeUndefined();
  });

  it("reports total/official/thirdParty and present category labels from referenceSummary", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      referenceSummary: {
        total: 5,
        official: 1,
        thirdParty: 4,
        categories: { official: 1, wikipedia: 1, ugc: 2, sns: 0 },
      },
    });

    expect(display.referenceSummary).toEqual({
      total: 5,
      official: 1,
      thirdParty: 4,
      presentCategoryLabels: ["公式", "Wikipedia", "UGC・投稿サイト"],
    });
  });

  it("reports an empty presentCategoryLabels when every category count is zero/absent", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      referenceSummary: { total: 0, official: 0, thirdParty: 0, categories: {} },
    });

    expect(display.referenceSummary?.presentCategoryLabels).toEqual([]);
  });

  it("REFERENCE_CATEGORY_LABELS covers every ReferenceCategory value with a Japanese label", () => {
    expect(REFERENCE_CATEGORY_LABELS).toEqual({
      official: "公式",
      wikipedia: "Wikipedia",
      sns: "SNS",
      ugc: "UGC・投稿サイト",
      news: "ニュース",
      media: "メディア",
      video: "動画",
      other: "その他",
    });
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
