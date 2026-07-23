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

function sectionKeysWithStatus(
  meta: AnalysisMeta,
  status: AnalysisSectionStatuses[keyof AnalysisSectionStatuses],
  exclude: (keyof AnalysisSectionStatuses)[] = [],
): (keyof AnalysisSectionStatuses)[] {
  return SECTION_ORDER.filter(
    (key) => !exclude.includes(key) && meta.sections[key] === status,
  );
}

// True when aiOverviewComparison's "real" status came from the
// DataForSEO Sandbox provider rather than from an actual document
// analysis (the way the other four sections' "real" status does).
// Sandbox is a connectivity-check response, not production SERP data
// (see getAiOverviewProviderStatusDisplay below) — lumping it into the
// same generic "実計算" bucket as the other sections would overstate
// what it represents, so the summary sentence calls it out separately.
function aiOverviewIsSandboxReal(meta: AnalysisMeta): boolean {
  return (
    meta.sections.aiOverviewComparison === "real" &&
    meta.aiOverviewProvider?.mode === "dataforseo"
  );
}

/**
 * A short sentence describing which sections are real, unavailable, or
 * still fixed placeholder data, e.g.
 * "共起語のみ実計算、その他は開発用データ" or
 * "共起語は取得失敗のため計算不能、その他は開発用データ".
 * When aiOverviewComparison is real via the DataForSEO Sandbox
 * provider, it's called out separately (e.g. "AI Overview比較は
 * DataForSEO Sandbox") instead of being folded into "のみ実計算",
 * since Sandbox results aren't production data (see
 * getAiOverviewProviderStatusDisplay).
 */
export function getSectionStatusSummary(meta: AnalysisMeta): string {
  const sandboxReal = aiOverviewIsSandboxReal(meta);
  const excludeFromReal = sandboxReal ? (["aiOverviewComparison"] as const) : [];

  const real = sectionKeysWithStatus(meta, "real", [...excludeFromReal]).map(
    (key) => SECTION_LABELS[key],
  );
  const unavailable = sectionKeysWithStatus(meta, "unavailable").map(
    (key) => SECTION_LABELS[key],
  );
  const mockCount =
    SECTION_ORDER.length - real.length - unavailable.length - (sandboxReal ? 1 : 0);

  if (!sandboxReal && real.length === 0 && unavailable.length === 0) {
    return "すべて開発用データ（ダミー）";
  }

  if (!sandboxReal && mockCount === 0 && unavailable.length === 0) {
    return "すべて実計算";
  }

  const parts: string[] = [];
  if (real.length > 0) parts.push(`${real.join("・")}のみ実計算`);
  if (sandboxReal) parts.push("AI Overview比較はDataForSEO Sandbox");
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

export interface AiOverviewProviderStatusDisplay {
  label: string;
  description: string;
  // Only present for the DataForSEO Sandbox success case — a stronger
  // warning that this is a connectivity-check response, not a real
  // production AI Overview / AI Mode result.
  caution?: string;
  tone: "neutral" | "caution";
}

/**
 * Describes which provider actually produced aiOverviewComparison, for
 * display near that section — so a DataForSEO Sandbox response (a
 * connectivity-check result, not real production SERP data; see
 * backend/services/dataforseo_client.py) is never mistaken for an
 * actual AI Overview / AI Mode result. Returns null when
 * meta.aiOverviewProvider isn't present (e.g. the client-side dummy
 * fallback in app/lib/dummy-data.ts, which predates this field).
 */
export function getAiOverviewProviderStatusDisplay(
  meta: AnalysisMeta,
): AiOverviewProviderStatusDisplay | null {
  const provider = meta.aiOverviewProvider;
  if (!provider) return null;

  if (provider.mode === "off") {
    return {
      label: "無効",
      description: "AI Overview比較は無効化されています。",
      tone: "neutral",
    };
  }

  if (provider.mode === "dataforseo") {
    if (provider.status === "real") {
      return {
        label: "DataForSEO Sandbox",
        description: "Sandbox接続結果です。本番SERPではありません。",
        caution:
          "DataForSEO Sandboxの接続確認結果です。本番のAI Overview / AI Mode結果ではありません。",
        tone: "caution",
      };
    }
    // status is always "unavailable" here (never "mock") — covers
    // missing credentials, DATAFORSEO_API_ENV=live (not implemented),
    // and a failed/empty Sandbox response alike. The precise reason is
    // in provider.reason (server logs/debugging), not surfaced here.
    return {
      label: "DataForSEO 未取得",
      description: "DataForSEOからAI Overview項目を取得できませんでした。",
      tone: "neutral",
    };
  }

  // mode === "mock"
  return {
    label: "開発用データ",
    description: "AI Overview比較は現在mockデータです。",
    tone: "neutral",
  };
}
