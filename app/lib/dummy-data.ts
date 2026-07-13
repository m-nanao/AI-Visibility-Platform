import type { AnalysisResult } from "./types";

/**
 * Builds a dummy AnalysisResult for the given brand name.
 * Consumed by the /api/analyze route handler until real data
 * sources (Common Crawl / DataForSEO / Python analysis API) are wired in.
 */
export function buildDummyAnalysis(brandName: string): AnalysisResult {
  return {
    brandName,
    meta: {
      // This is the Next.js-side fallback: nothing was actually
      // computed (not even cooccurrenceRanking), so every section is
      // "mock". documentsSource has no real meaning here (no
      // documents were processed at all) — "development_sample" is
      // used as the closest applicable value.
      sections: {
        summary: "mock",
        cooccurrenceRanking: "mock",
        contextAnalysis: "mock",
        aiOverviewComparison: "mock",
        improvements: "mock",
      },
      documentsSource: "development_sample",
      generatedAt: new Date().toISOString(),
    },
    summary: {
      brandName,
      visibilityScore: 62,
      totalMentions: 184,
      sentimentBreakdown: {
        positive: 58,
        neutral: 33,
        negative: 9,
      },
      topPlatforms: ["ChatGPT", "Perplexity", "Google AI Overview"],
      summaryText: `${brandName}は主要なAIチャットサービスにおいて中程度の認知度を持ち、直近30日間で言及数は増加傾向にあります。特に比較・レビュー系のプロンプトでの言及が目立ちます。`,
    },
    cooccurrenceRanking: [
      { keyword: "料金プラン", count: 42, trend: "up" },
      { keyword: "導入事例", count: 35, trend: "up" },
      { keyword: "競合比較", count: 29, trend: "flat" },
      { keyword: "サポート体制", count: 21, trend: "down" },
      { keyword: "API連携", count: 18, trend: "up" },
      { keyword: "口コミ・評判", count: 14, trend: "flat" },
    ],
    contextAnalysis: [
      {
        context: "比較検討フェーズ",
        description: "他社製品と並べて紹介されるケースが最も多く、価格と機能面での比較軸で語られています。",
        sentiment: "neutral",
        exampleQuote: `「${brandName}は他の類似サービスと比べて◯◯という特徴があります」`,
      },
      {
        context: "導入・活用事例",
        description: "実際の活用シーンに関する質問への回答で、好意的な文脈での言及が多く見られます。",
        sentiment: "positive",
        exampleQuote: `「${brandName}を使うことで業務効率が向上したという事例があります」`,
      },
      {
        context: "サポート・不満点",
        description: "サポート対応の遅さや学習コストについて言及される文脈で、やや否定的な評価も見られます。",
        sentiment: "negative",
        exampleQuote: `「${brandName}はサポート対応に時間がかかるという意見もあります」`,
      },
    ],
    aiOverviewComparison: [
      {
        platform: "Google AI Overview",
        mentioned: true,
        rank: 2,
        summary: "比較記事からの引用として2番目に表示されることが多い。",
      },
      {
        platform: "ChatGPT",
        mentioned: true,
        rank: 1,
        summary: "関連する質問に対して第一想起として挙げられる頻度が高い。",
      },
      {
        platform: "Perplexity",
        mentioned: true,
        rank: 3,
        summary: "情報源として公式サイトとレビューサイトが引用される傾向。",
      },
      {
        platform: "Copilot",
        mentioned: false,
        rank: null,
        summary: "現時点では明確な言及が確認されていません。",
      },
    ],
    improvements: [
      {
        title: "比較コンテンツの拡充",
        description: "競合比較の文脈での言及が多いため、公式サイトに詳細な比較表や導入メリットをまとめたページを用意すると引用されやすくなります。",
        priority: "high",
      },
      {
        title: "FAQ・サポート情報の構造化",
        description: "サポートに関するネガティブな言及を減らすため、よくある質問と回答をFAQ形式で整理し、AIが引用しやすい構造にすることを推奨します。",
        priority: "medium",
      },
      {
        title: "導入事例ページの強化",
        description: "好意的な文脈で引用されやすい導入事例を増やし、具体的な数値や業種別事例を追加すると認知度向上が期待できます。",
        priority: "medium",
      },
      {
        title: "Copilotでの露出強化",
        description: "Copilotでの言及がまだ少ないため、Bing/Microsoft系のインデックスに載りやすいコンテンツ配信を検討してください。",
        priority: "low",
      },
    ],
  };
}
