import type { AnalysisMeta, AnalysisSectionStatuses } from "./types";

const SECTION_LABELS: Record<keyof AnalysisSectionStatuses, string> = {
  summary: "サマリー",
  cooccurrenceRanking: "共起語",
  contextAnalysis: "文脈分析",
  aiOverviewComparison: "AI Overview比較",
  improvements: "改善提案",
};

const SECTION_ORDER: (keyof AnalysisSectionStatuses)[] = [
  "summary",
  "cooccurrenceRanking",
  "contextAnalysis",
  "aiOverviewComparison",
  "improvements",
];

/**
 * A short sentence describing which sections are real vs. still fixed
 * placeholder data, e.g. "共起語のみ実計算、その他は開発用データ".
 */
export function getSectionStatusSummary(meta: AnalysisMeta): string {
  const real = SECTION_ORDER.filter((key) => meta.sections[key] === "real").map(
    (key) => SECTION_LABELS[key],
  );

  if (real.length === 0) {
    return "すべて開発用データ（ダミー）";
  }

  if (real.length === SECTION_ORDER.length) {
    return "すべて実計算";
  }

  return `${real.join("・")}のみ実計算、その他は開発用データ`;
}
