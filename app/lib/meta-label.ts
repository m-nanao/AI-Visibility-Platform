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

function sectionLabelsWithStatus(
  meta: AnalysisMeta,
  status: AnalysisSectionStatuses[keyof AnalysisSectionStatuses],
): string[] {
  return SECTION_ORDER.filter((key) => meta.sections[key] === status).map(
    (key) => SECTION_LABELS[key],
  );
}

/**
 * A short sentence describing which sections are real, unavailable, or
 * still fixed placeholder data, e.g.
 * "共起語のみ実計算、その他は開発用データ" or
 * "共起語は取得失敗のため計算不能、その他は開発用データ".
 */
export function getSectionStatusSummary(meta: AnalysisMeta): string {
  const real = sectionLabelsWithStatus(meta, "real");
  const unavailable = sectionLabelsWithStatus(meta, "unavailable");
  const mockCount = SECTION_ORDER.length - real.length - unavailable.length;

  if (real.length === 0 && unavailable.length === 0) {
    return "すべて開発用データ（ダミー）";
  }

  if (mockCount === 0 && unavailable.length === 0) {
    return "すべて実計算";
  }

  const parts: string[] = [];
  if (real.length > 0) parts.push(`${real.join("・")}のみ実計算`);
  if (unavailable.length > 0) {
    parts.push(`${unavailable.join("・")}は取得失敗のため計算不能`);
  }
  if (mockCount > 0) parts.push("その他は開発用データ");

  return parts.join("、");
}

/**
 * A message to show in place of the co-occurrence ranking when it
 * couldn't be computed (e.g. every url in `urls` failed to fetch), so
 * this state isn't confused with "computed, but zero keywords found".
 * Returns null when the ranking is available (whether real or mock).
 */
export function getCooccurrenceUnavailableMessage(meta: AnalysisMeta): string | null {
  if (meta.sections.cooccurrenceRanking !== "unavailable") return null;
  return "URLを取得できなかったため共起解析を実行できませんでした";
}

/**
 * A short "N/M件成功" summary of meta.urlFetchResults, for display near
 * the co-occurrence section when documentsSource is "web_fetch". When
 * only some URLs succeeded, notes that the analysis only used the
 * pages that could be fetched, so it's clear the result isn't based
 * on everything the user asked for. Deliberately does not include the
 * per-URL error text — those are for server logs, not for surfacing
 * verbatim to end users.
 */
export function getUrlFetchSummary(meta: AnalysisMeta): string | null {
  if (!meta.urlFetchResults || meta.urlFetchResults.length === 0) return null;

  const total = meta.urlFetchResults.length;
  const successCount = meta.urlFetchResults.filter((r) => r.success).length;

  if (successCount > 0 && successCount < total) {
    return `URL取得: ${successCount}/${total}件成功（取得できたページのみで分析しています）`;
  }

  return `URL取得: ${successCount}/${total}件成功`;
}
