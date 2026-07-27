import type {
  AIOverviewComparisonItem,
  AiOverviewEnvironment,
  AnalysisMeta,
  AnalysisSectionStatuses,
} from "./types";

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

/**
 * The concrete data source behind aiOverviewComparison, preferring
 * meta.aiOverviewProvider.environment when the backend sent it.
 * Falls back to inferring from mode/status for a response from an
 * older backend that only knows about those two fields — in that
 * fallback case, a dataforseo+real result is assumed to be "sandbox"
 * (the only real dataforseo path that existed before `environment` was
 * introduced), since it can't be told apart from "live" any other way.
 * Returns null when meta.aiOverviewProvider isn't present at all (e.g.
 * the client-side dummy fallback in app/lib/dummy-data.ts).
 */
function resolveAiOverviewEnvironment(meta: AnalysisMeta): AiOverviewEnvironment | null {
  const provider = meta.aiOverviewProvider;
  if (!provider) return null;
  if (provider.environment) return provider.environment;

  if (provider.mode === "off") return "off";
  if (provider.mode === "mock") return "mock";
  // mode === "dataforseo"
  return provider.status === "real" ? "sandbox" : "unavailable";
}

const SANDBOX_OR_LIVE_SUMMARY_LABELS: Record<"sandbox" | "live", string> = {
  sandbox: "AI Overview比較はDataForSEO Sandbox",
  live: "AI Overview比較はDataForSEO Live",
};

/**
 * A short sentence describing which sections are real, unavailable, or
 * still fixed placeholder data, e.g.
 * "共起語のみ実計算、その他は開発用データ" or
 * "共起語は取得失敗のため計算不能、その他は開発用データ".
 * When aiOverviewComparison is real via the DataForSEO Sandbox or Live
 * provider, it's called out separately (e.g. "AI Overview比較は
 * DataForSEO Sandbox"/"...DataForSEO Live") instead of being folded
 * into "のみ実計算", since neither represents the same kind of
 * computation as the other four sections (see
 * getAiOverviewProviderStatusDisplay for why Sandbox/Live get their
 * own explanation).
 */
export function getSectionStatusSummary(meta: AnalysisMeta): string {
  const environment = resolveAiOverviewEnvironment(meta);
  const isSandboxOrLiveReal =
    meta.sections.aiOverviewComparison === "real" &&
    (environment === "sandbox" || environment === "live");
  const excludeFromReal = isSandboxOrLiveReal ? (["aiOverviewComparison"] as const) : [];

  const real = sectionKeysWithStatus(meta, "real", [...excludeFromReal]).map(
    (key) => SECTION_LABELS[key],
  );
  const unavailable = sectionKeysWithStatus(meta, "unavailable").map(
    (key) => SECTION_LABELS[key],
  );
  const mockCount =
    SECTION_ORDER.length - real.length - unavailable.length - (isSandboxOrLiveReal ? 1 : 0);

  if (!isSandboxOrLiveReal && real.length === 0 && unavailable.length === 0) {
    return "すべて開発用データ（ダミー）";
  }

  if (!isSandboxOrLiveReal && mockCount === 0 && unavailable.length === 0) {
    return "すべて実計算";
  }

  const parts: string[] = [];
  if (real.length > 0) parts.push(`${real.join("・")}のみ実計算`);
  if (isSandboxOrLiveReal && (environment === "sandbox" || environment === "live")) {
    parts.push(SANDBOX_OR_LIVE_SUMMARY_LABELS[environment]);
  }
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
  // Present for the DataForSEO Sandbox and Live success cases — a
  // stronger warning distinguishing a connectivity-check response
  // (Sandbox) from a real, potentially-billed production result (Live).
  caution?: string;
  tone: "neutral" | "caution";
}

/**
 * Describes which provider actually produced aiOverviewComparison, for
 * display near that section — so a DataForSEO Sandbox response (a
 * connectivity-check result, not real production SERP data; see
 * backend/services/dataforseo_client.py) is never mistaken for a real
 * DataForSEO Live result, or for mock data. Returns null when
 * meta.aiOverviewProvider isn't present (e.g. the client-side dummy
 * fallback in app/lib/dummy-data.ts, which predates this field).
 */
export function getAiOverviewProviderStatusDisplay(
  meta: AnalysisMeta,
): AiOverviewProviderStatusDisplay | null {
  const environment = resolveAiOverviewEnvironment(meta);
  if (environment === null) return null;

  switch (environment) {
    case "off":
      return {
        label: "無効",
        description: "AI Overview比較は無効化されています。",
        tone: "neutral",
      };

    case "live":
      return {
        label: "DataForSEO Live",
        description: "DataForSEO Live APIによる本番SERP取得結果です。",
        caution:
          "この結果は実APIリクエストに基づきます。DataForSEO側で費用が発生する可能性があります。",
        tone: "caution",
      };

    case "sandbox":
      return {
        label: "DataForSEO Sandbox",
        description: "Sandbox接続結果です。本番SERPではありません。",
        caution:
          "DataForSEO Sandboxの接続確認結果です。本番のAI Overview / AI Mode結果ではありません。",
        tone: "caution",
      };

    case "unavailable":
      // Covers missing credentials, insufficient Live manual-check
      // gates, and a failed/empty Sandbox or Live response alike. The
      // precise reason is in provider.reason (server logs/debugging),
      // not surfaced here.
      return {
        label: "DataForSEO 未取得",
        description: "DataForSEOからAI Overview項目を取得できませんでした。",
        tone: "neutral",
      };

    case "mock":
    default:
      return {
        label: "開発用データ",
        description: "AI Overview比較は現在mockデータです。",
        tone: "neutral",
      };
  }
}

// Kept in sync with backend/services/dataforseo_client.py's
// _MAX_REFERENCES — the backend already caps references at this count,
// but this is enforced again here so the UI never renders more even if
// a future/older backend response happens to include extras.
const MAX_DISPLAYED_REFERENCES = 10;

export interface AIOverviewReferenceDisplay {
  // What to show as the primary label for one reference — the domain
  // when present (the common case), falling back to the url, then the
  // title, so a reference with only a partial shape is still shown
  // rather than dropped (see backend AIOverviewReference — every field
  // is optional).
  label: string;
  title?: string;
  url?: string;
}

export type OwnDomainReferenceStatus = "included" | "not_included" | "unjudged";

export interface AiOverviewItemDetailDisplay {
  // Whether a "詳細を見る" toggle should be offered at all.
  hasDetail: boolean;
  detailText?: string;
  // Already capped at MAX_DISPLAYED_REFERENCES and ready to render as-is.
  references: AIOverviewReferenceDisplay[];
  // "unjudged" covers both "no input urls were given" and "no
  // references were found" — both mean there's nothing to conclude
  // from, so the UI shows neither a positive nor a negative statement.
  ownDomainStatus: OwnDomainReferenceStatus;
}

export const OWN_DOMAIN_STATUS_LABELS: Record<"included" | "not_included", string> = {
  included: "自社サイトが参照元に含まれています",
  not_included: "自社サイトは参照元に確認できません",
};

/**
 * Reduces one AIOverviewComparisonItem's optional detail fields
 * (fullSummary/references/ownDomainReferenced — only ever populated by
 * the DataForSEO provider, see backend/services/ai_overview_provider.py)
 * to exactly what AIOverviewComparisonSection needs to render, so the
 * component itself stays presentation-only. Every field on the input
 * item is optional — an item with none of them (mock data, or an older
 * backend response) yields hasDetail=false, references=[],
 * ownDomainStatus="unjudged", which the section renders as "no change"
 * from the pre-existing summary-only display.
 */
export function getAiOverviewItemDetailDisplay(
  item: AIOverviewComparisonItem,
): AiOverviewItemDetailDisplay {
  const references = (item.references ?? [])
    .slice(0, MAX_DISPLAYED_REFERENCES)
    .map((reference) => ({
      label: reference.domain ?? reference.url ?? reference.title ?? "不明な参照元",
      title: reference.title,
      url: reference.url,
    }));

  let ownDomainStatus: OwnDomainReferenceStatus = "unjudged";
  if (item.ownDomainReferenced === true) ownDomainStatus = "included";
  else if (item.ownDomainReferenced === false) ownDomainStatus = "not_included";

  return {
    hasDetail: Boolean(item.fullSummary),
    detailText: item.fullSummary,
    references,
    ownDomainStatus,
  };
}
