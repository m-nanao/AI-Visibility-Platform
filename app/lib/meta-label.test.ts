import { describe, expect, it } from "vitest";
import {
  OWN_DOMAIN_STATUS_LABELS,
  REFERENCE_CATEGORY_LABELS,
  getAiOverviewItemDetailDisplay,
  getAiOverviewProviderStatusDisplay,
  getAnalysisSourceBreakdownDisplay,
  getCommonCrawlProviderDisplay,
  getCooccurrenceUnavailableMessage,
  getSectionStatusSummary,
  getUrlFetchSummary,
} from "./meta-label";
import { buildDummyAnalysis } from "./dummy-data";
import type { AIOverviewComparisonItem, AnalysisMeta } from "./types";

function baseMeta(): AnalysisMeta {
  return buildDummyAnalysis("OpenAI").meta;
}

// Padding used to push a test fullSummary past meta-label.ts's
// INLINE_FULL_SUMMARY_MAX_LENGTH (600 chars), so tests that exercise the
// summary + "続きを見る" continuation-toggle path aren't instead routed
// through the "short fullSummary shown in full" inline path. ~880 chars
// on its own, comfortably past 600 even combined with a short prefix.
const LONG_FILLER =
  " Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod tempor incididunt ut labore et dolore magna aliqua ut enim ad minim veniam quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore eu fugiat nulla pariatur excepteur sint occaecat cupidatat non proident sunt in culpa qui officia deserunt mollit anim id est laborum." +
  " Sed ut perspiciatis unde omnis iste natus error sit voluptatem accusantium doloremque laudantium totam rem aperiam eaque ipsa quae ab illo inventore veritatis et quasi architecto beatae vitae dicta sunt explicabo.";

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

  it("reports no continuation/references and an unjudged own-domain status for a plain (e.g. mock) item", () => {
    const display = getAiOverviewItemDetailDisplay(baseItem());

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
    expect(display.references).toEqual([]);
    expect(display.ownDomainStatus).toBe("unjudged");
  });

  it("shows a short fullSummary in full, with no continuation toggle, when it isn't a clean prefix match of summary", () => {
    // summary ends in "." while fullSummary's corresponding character is
    // "," (a plausible real-world divergence from markdown cleanup) —
    // not a clean prefix, but short enough (<= INLINE_FULL_SUMMARY_MAX_LENGTH)
    // to be shown in full up front rather than hidden behind a toggle.
    const fullSummary = "Acme is a well-reviewed tool for teams, used by hundreds of companies.";
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
    expect(display.displaySummary).toBe(fullSummary);
  });

  it("falls back to the full fullSummary as the continuation when it's long and isn't a clean prefix match of summary", () => {
    // Same shape as above, but padded past INLINE_FULL_SUMMARY_MAX_LENGTH
    // so the summary + continuation-toggle path is exercised instead of
    // the inline-short-fullSummary path.
    const fullSummary =
      "Acme is a well-reviewed tool for teams, used by hundreds of companies." + LONG_FILLER;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(fullSummary);
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

  it("OWN_DOMAIN_STATUS_LABELS clearly states 自社公式サイト for both included and not_included", () => {
    expect(OWN_DOMAIN_STATUS_LABELS.included).toBe(
      "自社公式サイトがAI Overviewの参照元に含まれています",
    );
    expect(OWN_DOMAIN_STATUS_LABELS.not_included).toBe(
      "自社公式サイトはAI Overviewの参照元に確認できません",
    );
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
    // (fullSummary shown in full since it's short, references with url
    // usable as href, own-domain note).
    const display = getAiOverviewItemDetailDisplay(item);
    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe(item.fullSummary);
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

  it("reports total/official/thirdParty and category counts from referenceSummary", () => {
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
      categoryCounts: [
        { label: "公式", count: 1 },
        { label: "Wikipedia", count: 1 },
        { label: "UGC・投稿サイト", count: 2 },
      ],
    });
  });

  it("excludes categories with a count of 0 from categoryCounts", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      referenceSummary: {
        total: 2,
        official: 1,
        thirdParty: 1,
        categories: { official: 1, sns: 1, wikipedia: 0, ugc: 0 },
      },
    });

    const labels = display.referenceSummary?.categoryCounts.map((c) => c.label);
    expect(labels).toEqual(["公式", "SNS"]);
    expect(labels).not.toContain("Wikipedia");
    expect(labels).not.toContain("UGC・投稿サイト");
  });

  it("includes every category with at least one reference in categoryCounts", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      referenceSummary: {
        total: 10,
        official: 5,
        thirdParty: 5,
        categories: { official: 5, wikipedia: 1, sns: 1, other: 3 },
      },
    });

    expect(display.referenceSummary?.categoryCounts).toEqual([
      { label: "公式", count: 5 },
      { label: "Wikipedia", count: 1 },
      { label: "SNS", count: 1 },
      { label: "その他", count: 3 },
    ]);
  });

  it("reports an empty categoryCounts when every category count is zero/absent", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      referenceSummary: { total: 0, official: 0, thirdParty: 0, categories: {} },
    });

    expect(display.referenceSummary?.categoryCounts).toEqual([]);
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

describe("getAiOverviewItemDetailDisplay — continuation text (続きを見る)", () => {
  function baseItem(): AIOverviewComparisonItem {
    return {
      platform: "ChatGPT (OpenAI API)",
      mentioned: true,
      rank: null,
      summary: "Acme is a well-reviewed tool for teams.",
    };
  }

  it("has no continuation when fullSummary is absent", () => {
    const display = getAiOverviewItemDetailDisplay(baseItem());
    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
  });

  it("has no continuation when fullSummary equals summary exactly", () => {
    const text = "Acme is a well-reviewed tool for teams.";
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: text,
      fullSummary: text,
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
  });

  it("has no continuation when fullSummary only differs from summary by whitespace/newlines", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Acme is a well-reviewed tool for teams.",
      fullSummary: "Acme is a well-reviewed tool\nfor teams.",
    });

    expect(display.hasContinuation).toBe(false);
  });

  it("extracts only the part of fullSummary after summary's shared prefix", () => {
    const prefix = "Acme is a tool for teams and provides";
    const rest =
      " comprehensive support to organizations of all sizes across many different industries and regions worldwide." +
      LONG_FILLER;
    const fullSummary = prefix + rest;
    const summary = `${prefix}…`;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
    // The continuation must not repeat summary's own text.
    expect(display.continuationText).not.toContain(prefix);
  });

  it("treats a trailing ... (three dots) the same as … when matching summary's prefix", () => {
    const prefix = "Acme is a tool for teams and provides";
    const rest =
      " reliable, well-documented support for organizations of every size across many regions." + LONG_FILLER;
    const fullSummary = prefix + rest;
    const summary = `${prefix}...`;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
  });

  it("maps a matched prefix across a paragraph break (\\n\\n) back to the correct position in the original fullSummary", () => {
    // fullSummary keeps a "\n\n" paragraph break (as dataforseo_client.py's
    // fullSummary does) where summary has it flattened to a single space —
    // the "\n\n" run must count as exactly one normalized character, or
    // the cut point drifts and the continuation starts one character early.
    const prefix = "Acme is a tool for teams.\n\nIt provides";
    const rest =
      " comprehensive support to organizations of all sizes across many different industries and regions worldwide." +
      LONG_FILLER;
    const fullSummary = prefix + rest;
    const summary = "Acme is a tool for teams. It provides…";

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
  });

  it("uses the full fullSummary as the continuation when summary is absent but fullSummary is long enough", () => {
    const fullSummary =
      "Acme is generally recognized as a reliable collaboration tool used by teams across many industries." +
      LONG_FILLER;

    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: undefined,
      fullSummary,
    });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(fullSummary);
  });

  it("has no continuation when summary is absent and fullSummary is too short to be worth a toggle", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: undefined,
      fullSummary: "Acme is a small tool.",
    });

    expect(display.hasContinuation).toBe(false);
  });

  it("has no continuation when the remaining continuation is shorter than the minimum length threshold", () => {
    // Padded past INLINE_FULL_SUMMARY_MAX_LENGTH so this exercises
    // buildContinuationText's own MIN_CONTINUATION_LENGTH gate, not the
    // "short fullSummary shown in full" inline path.
    const prefix = "Acme is a well reviewed and widely used collaboration tool for teams" + LONG_FILLER;
    const fullSummary = `${prefix} today.`; // remaining text is only a few characters
    const summary = prefix;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
  });

  it("shows a continuation once it reaches the minimum length threshold", () => {
    const prefix = "Acme is a well reviewed and widely used collaboration tool for teams" + LONG_FILLER;
    const rest = " that has been adopted by many organizations worldwide for its reliability.";
    const fullSummary = prefix + rest;
    const summary = prefix;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
  });

  it("does not affect references/referenceSummary/ownDomainReferenced display when a continuation is present", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      fullSummary:
        "Acme is a well-reviewed tool for teams. It has strong customer support and a large user base worldwide.",
      references: [{ domain: "acme.example.com", category: "official" }],
      referenceSummary: { total: 1, official: 1, thirdParty: 0, categories: { official: 1 } },
      ownDomainReferenced: true,
    });

    expect(display.references).toEqual([
      { label: "acme.example.com", title: undefined, url: undefined, categoryLabel: "公式" },
    ]);
    expect(display.referenceSummary).toEqual({
      total: 1,
      official: 1,
      thirdParty: 0,
      categoryCounts: [{ label: "公式", count: 1 }],
    });
    expect(display.ownDomainStatus).toBe("included");
  });
});

describe("getAiOverviewItemDetailDisplay — displaySummary ellipsis handling", () => {
  function baseItem(): AIOverviewComparisonItem {
    return {
      platform: "ChatGPT (OpenAI API)",
      mentioned: true,
      rank: null,
      summary: "Vercelはクラウドサービスです",
    };
  }

  it("keeps summary's trailing … as-is when there is a continuation", () => {
    const prefix = "Vercelはクラウドサービスを提供するプラットフォームで多くの開発者に利用されています";
    const rest = "。フロントエンド開発者向けの高速なデプロイとホスティングを強みとしています。" + LONG_FILLER;
    const summary = `${prefix}…`;
    const fullSummary = prefix + rest;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.displaySummary).toBe(summary);
  });

  it("keeps summary's trailing ... as-is when there is a continuation", () => {
    const prefix = "Vercelはクラウドサービスを提供するプラットフォームで多くの開発者に利用されています";
    const rest = "。フロントエンド開発者向けの高速なデプロイとホスティングを強みとしています。" + LONG_FILLER;
    const summary = `${prefix}...`;
    const fullSummary = prefix + rest;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.displaySummary).toBe(summary);
  });

  it("strips a trailing … from summary when there is no continuation (no fullSummary at all)", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Vercelはクラウドサービスです…",
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe("Vercelはクラウドサービスです");
  });

  it("strips a trailing ... from summary when there is no continuation", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Vercelはクラウドサービスです...",
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe("Vercelはクラウドサービスです");
  });

  it("shows the full fullSummary (not the ellipsis-stripped summary) when fullSummary is only slightly longer than summary (the 201 vs 214 char case)", () => {
    // Mirrors the real-world case that originally prompted the ellipsis
    // stripping fix: summary and fullSummary are close in length. Now
    // that a short fullSummary (<= INLINE_FULL_SUMMARY_MAX_LENGTH) is
    // shown in full up front, the extra detail in fullSummary ("、少し
    // 詳しく。") is no longer silently dropped in favor of summary.
    const summary = "Vercelはクラウドサービスです…";
    const fullSummary = "Vercelはクラウドサービスです、少し詳しく。";

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
    expect(display.displaySummary).toBe(fullSummary);
  });

  it("does not touch a mid-sentence … that isn't at the very end", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Vercelは…とても人気のあるサービスです",
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe("Vercelは…とても人気のあるサービスです");
  });

  it("leaves a normal sentence-ending summary (no ellipsis) unchanged", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Vercelはクラウドサービスです。",
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe("Vercelはクラウドサービスです。");
  });

  it("does not affect references/referenceSummary/ownDomainReferenced display", () => {
    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      summary: "Acme is a well-reviewed tool…",
      references: [{ domain: "acme.example.com", category: "official" }],
      referenceSummary: { total: 1, official: 1, thirdParty: 0, categories: { official: 1 } },
      ownDomainReferenced: true,
    });

    expect(display.displaySummary).toBe("Acme is a well-reviewed tool");
    expect(display.references).toEqual([
      { label: "acme.example.com", title: undefined, url: undefined, categoryLabel: "公式" },
    ]);
    expect(display.referenceSummary).toEqual({
      total: 1,
      official: 1,
      thirdParty: 0,
      categoryCounts: [{ label: "公式", count: 1 }],
    });
    expect(display.ownDomainStatus).toBe("included");
  });
});

describe("getAiOverviewItemDetailDisplay — inline short fullSummary (no mid-sentence 続きを見る)", () => {
  function baseItem(): AIOverviewComparisonItem {
    return {
      platform: "ChatGPT (OpenAI API)",
      mentioned: true,
      rank: null,
      summary: "Next....",
    };
  }

  it("shows fullSummary in full as displaySummary when it's at or below the inline threshold (600 chars)", () => {
    const fullSummary =
      "Next.jsの主要な開発元／メンテナーとしての位置付けでも認識されています。";

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(display.displaySummary).toBe(fullSummary);
  });

  it("reports hasContinuation=false for a short fullSummary, even though it differs a lot from summary", () => {
    const fullSummary =
      "Next.jsの主要な開発元／メンテナーとしての位置付けでも認識されています。";

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(display.hasContinuation).toBe(false);
  });

  it("reports continuationText=undefined for a short fullSummary", () => {
    const fullSummary =
      "Next.jsの主要な開発元／メンテナーとしての位置付けでも認識されています。";

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(display.continuationText).toBeUndefined();
  });

  it("falls through to the existing summary + continuation-toggle behavior once fullSummary exceeds the inline threshold", () => {
    const prefix = "Acme is a tool for teams and provides";
    const rest =
      " comprehensive support to organizations of all sizes across many different industries and regions worldwide." +
      LONG_FILLER;
    const fullSummary = prefix + rest;
    const summary = `${prefix}…`;

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary, fullSummary });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
    expect(display.displaySummary).toBe(summary);
  });

  it("keeps existing summary-only display when fullSummary is absent", () => {
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary: "普通の文章です。" });

    expect(display.hasContinuation).toBe(false);
    expect(display.continuationText).toBeUndefined();
    expect(display.displaySummary).toBe("普通の文章です。");
  });

  it("keeps stripping summary's trailing 省略記号 when there is no fullSummary at all (existing behavior preserved)", () => {
    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary: "普通の文章です…" });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe("普通の文章です");
  });

  it("shows a long (>600 char) DataForSEO-style fullSummary via the continuation toggle without breaking existing display", () => {
    const prefix = "Acme is a well-reviewed collaboration tool for teams";
    const rest =
      " that has been adopted by many organizations worldwide, offering broad integrations and reliable customer support." +
      LONG_FILLER;
    const fullSummary = prefix + rest;
    const summary = `${prefix}…`;

    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      platform: "Google AI Mode (DataForSEO Sandbox)",
      summary,
      fullSummary,
      references: [{ domain: "acme.example.com", category: "official" }],
      referenceSummary: { total: 1, official: 1, thirdParty: 0, categories: { official: 1 } },
      ownDomainReferenced: true,
    });

    expect(display.hasContinuation).toBe(true);
    expect(display.continuationText).toBe(rest.trim());
    expect(display.references).toEqual([
      { label: "acme.example.com", title: undefined, url: undefined, categoryLabel: "公式" },
    ]);
    expect(display.referenceSummary).toEqual({
      total: 1,
      official: 1,
      thirdParty: 0,
      categoryCounts: [{ label: "公式", count: 1 }],
    });
    expect(display.ownDomainStatus).toBe("included");
  });

  it("shows a short DataForSEO-style fullSummary in full without breaking references/referenceSummary/ownDomainReferenced display", () => {
    const fullSummary = "Acme is a well-reviewed collaboration tool used by many teams.";

    const display = getAiOverviewItemDetailDisplay({
      ...baseItem(),
      platform: "Google AI Mode (DataForSEO Sandbox)",
      fullSummary,
      references: [{ domain: "acme.example.com", category: "official" }],
      referenceSummary: { total: 1, official: 1, thirdParty: 0, categories: { official: 1 } },
      ownDomainReferenced: true,
    });

    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe(fullSummary);
    expect(display.references).toEqual([
      { label: "acme.example.com", title: undefined, url: undefined, categoryLabel: "公式" },
    ]);
    expect(display.referenceSummary).toEqual({
      total: 1,
      official: 1,
      thirdParty: 0,
      categoryCounts: [{ label: "公式", count: 1 }],
    });
    expect(display.ownDomainStatus).toBe("included");
  });

  it("treats a fullSummary exactly at the inline threshold length as short (inclusive boundary)", () => {
    const fullSummary = "字".repeat(600);

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), fullSummary });

    expect(fullSummary.length).toBe(600);
    expect(display.hasContinuation).toBe(false);
    expect(display.displaySummary).toBe(fullSummary);
  });

  it("treats a fullSummary one character past the inline threshold as long", () => {
    const fullSummary = "字".repeat(601);

    const display = getAiOverviewItemDetailDisplay({ ...baseItem(), summary: "字".repeat(600), fullSummary });

    expect(fullSummary.length).toBe(601);
    expect(display.hasContinuation).toBe(false); // remaining continuation is only 1 char — below MIN_CONTINUATION_LENGTH
    expect(display.continuationText).toBeUndefined();
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

// Added 2026-07-28 (style/analysis-source-breakdown) — combines the
// Webページ (urlFetchResults) and Common Crawl補完 (commonCrawlProvider)
// counts into one "分析ソース内訳" line, so it's obvious at a glance how
// many Documents came from each source in the same analysis.
describe("getAnalysisSourceBreakdownDisplay", () => {
  it("returns null when there are no url fetch results and no common crawl provider", () => {
    expect(getAnalysisSourceBreakdownDisplay(baseMeta())).toBeNull();
  });

  it("shows only the web page count when Common Crawl is off", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [{ url: "https://example.com/a", success: true }],
      commonCrawlProvider: {
        mode: "off",
        status: "off",
        reason: "Common Crawl integration is off.",
      },
    };

    expect(getAnalysisSourceBreakdownDisplay(meta)).toBe("Webページ 1件");
  });

  it("shows only the web page count when meta.commonCrawlProvider isn't present at all", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [{ url: "https://example.com/a", success: true }],
    };

    expect(getAnalysisSourceBreakdownDisplay(meta)).toBe("Webページ 1件");
  });

  it("combines web page and common crawl counts on a full success", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [{ url: "https://cybozu.co.jp/about", success: true }],
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 3 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-25",
        candidateCount: 5,
        documentCount: 3,
      },
    };

    expect(getAnalysisSourceBreakdownDisplay(meta)).toBe(
      "Webページ 1件 / Common Crawl補完 3件",
    );
  });

  it("shows only the common crawl count when there are no url fetch results", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 1 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-25",
        candidateCount: 1,
        documentCount: 1,
      },
    };

    expect(getAnalysisSourceBreakdownDisplay(meta)).toBe("Common Crawl補完 1件");
  });

  it("excludes common crawl from the breakdown when it's unavailable, keeping only the web page count", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [{ url: "https://cybozu.co.jp/about", success: true }],
      commonCrawlProvider: {
        mode: "domain",
        status: "unavailable",
        reason: "Common Crawl found candidates but none could be fetched into a usable document.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-25",
        candidateCount: 5,
      },
    };

    expect(getAnalysisSourceBreakdownDisplay(meta)).toBe("Webページ 1件");
  });

  it("never renders HTML or WARC body text", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      urlFetchResults: [{ url: "https://cybozu.co.jp/about", success: true }],
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 2 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-25",
        candidateCount: 2,
        documentCount: 2,
      },
    };

    const breakdown = getAnalysisSourceBreakdownDisplay(meta) ?? "";
    expect(breakdown).not.toContain("<html");
    expect(breakdown).not.toContain("WARC/1.0");
  });
});

describe("getCommonCrawlProviderDisplay", () => {
  it("returns null when meta.commonCrawlProvider is absent (older backend / client dummy fallback)", () => {
    expect(getCommonCrawlProviderDisplay(baseMeta())).toBeNull();
  });

  it("shows an off summary with no detail", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "off",
        status: "off",
        reason: "Common Crawl integration is off.",
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)).toEqual({
      summary: "Common Crawl補完: オフ",
    });
  });

  it("shows an off summary when disabled server-side, even if mode is domain", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "off",
        reason: "Common Crawl is disabled (COMMON_CRAWL_ENABLED is not true).",
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)?.summary).toBe("Common Crawl補完: オフ");
  });

  it("shows a document count and domain/index detail on success", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 1 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-08",
        candidateCount: 3,
        documentCount: 1,
      },
    };

    const display = getCommonCrawlProviderDisplay(meta);
    expect(display?.summary).toBe("Common Crawl補完: 取得済み（1件）");
    expect(display?.detail).toBe("対象ドメイン: cybozu.co.jp / Index: CC-MAIN-2026-08");
  });

  it("omits detail on success when domain/crawlIndex aren't present", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 1 document(s).",
        documentCount: 1,
      },
    };

    const display = getCommonCrawlProviderDisplay(meta);
    expect(display?.summary).toBe("Common Crawl補完: 取得済み（1件）");
    expect(display?.detail).toBeUndefined();
  });

  it("shows the reason on an unavailable result", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "unavailable",
        reason: "Common Crawl domain could not be determined from commonCrawlDomain or urls.",
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)?.summary).toBe(
      "Common Crawl補完: 未取得（理由: Common Crawl domain could not be determined from commonCrawlDomain or urls.）",
    );
  });

  it("never renders HTML or WARC body text — meta.commonCrawlProvider has no field for either", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 1 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-08",
        candidateCount: 1,
        documentCount: 1,
      },
    };

    const display = getCommonCrawlProviderDisplay(meta);
    const rendered = `${display?.summary ?? ""} ${display?.detail ?? ""}`;
    expect(rendered).not.toContain("<html");
    expect(rendered).not.toContain("WARC/1.0");
  });

  // Added 2026-07-28 (feature/common-crawl-multiple-documents) — Common
  // Crawl補完 now can add up to 3 Documents per request (see
  // backend/main.py's COMMON_CRAWL_MAX_DOCUMENTS_PER_ANALYZE); this
  // display function was already generic on documentCount, so these
  // just lock in that behavior for the new, larger counts.
  it("shows a document count of 3 when the full cap is reached", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl added 3 document(s) for cybozu.co.jp.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-08",
        candidateCount: 5,
        documentCount: 3,
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)?.summary).toBe(
      "Common Crawl補完: 取得済み（3件）",
    );
  });

  it("shows a document count of 2 on a partial success", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "real",
        reason: "Common Crawl completed with partial results (2 document(s) for cybozu.co.jp).",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-08",
        candidateCount: 2,
        documentCount: 2,
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)?.summary).toBe(
      "Common Crawl補完: 取得済み（2件）",
    );
  });

  it("does not break when documentCount is 0 on an unavailable result", () => {
    const meta: AnalysisMeta = {
      ...baseMeta(),
      commonCrawlProvider: {
        mode: "domain",
        status: "unavailable",
        reason: "Common Crawl found candidates but none could be fetched into a usable document.",
        domain: "cybozu.co.jp",
        crawlIndex: "CC-MAIN-2026-08",
        candidateCount: 5,
        documentCount: 0,
      },
    };

    expect(getCommonCrawlProviderDisplay(meta)?.summary).toBe(
      "Common Crawl補完: 未取得（理由: Common Crawl found candidates but none could be fetched into a usable document.）",
    );
  });
});
