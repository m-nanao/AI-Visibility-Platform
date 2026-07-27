import type {
  AIOverviewComparisonItem,
  AiOverviewEnvironment,
  AnalysisMeta,
  AnalysisSectionStatuses,
  ReferenceCategory,
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

// Display label per ReferenceCategory — see backend
// services/ai_overview_provider.py's _classify_reference_category()
// for how a reference is assigned one of these (rule-based, not exact).
export const REFERENCE_CATEGORY_LABELS: Record<ReferenceCategory, string> = {
  official: "公式",
  wikipedia: "Wikipedia",
  sns: "SNS",
  ugc: "UGC・投稿サイト",
  news: "ニュース",
  media: "メディア",
  video: "動画",
  other: "その他",
};

// Canonical display order for a reference summary's "主な分類" list —
// not count-sorted, so the order stays stable across responses.
const REFERENCE_CATEGORY_DISPLAY_ORDER: ReferenceCategory[] = [
  "official",
  "wikipedia",
  "news",
  "media",
  "ugc",
  "sns",
  "video",
  "other",
];

export interface AIOverviewReferenceDisplay {
  // What to show as the primary label for one reference — the domain
  // when present (the common case), falling back to the url, then the
  // title, so a reference with only a partial shape is still shown
  // rather than dropped (see backend AIOverviewReference — every field
  // is optional).
  label: string;
  title?: string;
  url?: string;
  // Undefined when the backend didn't classify this reference (older
  // response, or a shape _classify_reference_category couldn't read).
  categoryLabel?: string;
}

export interface AiOverviewReferenceCategoryCountDisplay {
  label: string;
  count: number;
}

export interface AiOverviewReferenceSummaryDisplay {
  total: number;
  official: number;
  thirdParty: number;
  // One entry per category with at least one reference, in
  // REFERENCE_CATEGORY_DISPLAY_ORDER (not count-sorted) — ready to
  // render as "label count" badges.
  categoryCounts: AiOverviewReferenceCategoryCountDisplay[];
}

export type OwnDomainReferenceStatus = "included" | "not_included" | "unjudged";

export interface AiOverviewItemDetailDisplay {
  // Whether a "続きを見る" toggle should be offered at all — true only
  // when fullSummary has a genuinely new continuation beyond what
  // summary already shows (see buildContinuationText below). False for
  // plain mock/older-backend items (no fullSummary), for a fullSummary
  // that's essentially the same text as summary, and for a fullSummary
  // whose remaining continuation is too short to be worth a toggle.
  hasContinuation: boolean;
  continuationText?: string;
  // What to render in place of item.summary directly. Equal to
  // item.summary as-is when hasContinuation is true (the trailing
  // "…"/"..." correctly signals more text is available behind the
  // toggle); with that trailing ellipsis stripped when hasContinuation
  // is false, so a summary that happens to end in "…" doesn't read as
  // "truncated" when there's nothing more to show.
  displaySummary: string;
  // Already capped at MAX_DISPLAYED_REFERENCES and ready to render as-is.
  references: AIOverviewReferenceDisplay[];
  // Undefined when the item has no references to summarize (mock data,
  // an older backend response, or a dataforseo item with 0 references).
  referenceSummary?: AiOverviewReferenceSummaryDisplay;
  // "unjudged" covers both "no input urls were given" and "no
  // references were found" — both mean there's nothing to conclude
  // from, so the UI shows neither a positive nor a negative statement.
  ownDomainStatus: OwnDomainReferenceStatus;
}

// Below this length, a "続きを見る" toggle would reveal only a sliver of
// text — not worth the extra click. Applies both to a continuation
// sliced out of fullSummary and to a fullSummary shown in full (no
// summary to compare against).
const MIN_CONTINUATION_LENGTH = 30;

// Collapses all whitespace runs (including newlines) to a single space
// and trims, so paragraph-break differences between summary (always
// single-line, see backend/services/dataforseo_client.py's
// _clean_markdown / chatgpt_client.py's _summarize) and fullSummary
// (keeps line breaks) don't defeat a prefix comparison.
function normalizeForComparison(text: string): string {
  return text.replace(/\s+/g, " ").trim();
}

// summary is truncated with a trailing "…" (or, defensively, "...")
// when the source text was cut off — see _SUMMARY_MAX_CHARS in both
// dataforseo_client.py and chatgpt_client.py. Stripped before prefix
// comparison since fullSummary's corresponding text has no such marker
// at that position (it keeps going).
function stripTrailingEllipsis(text: string): string {
  return text.replace(/\s*(\.{3,}|…)\s*$/u, "");
}

// Like stripTrailingEllipsis, but for direct display rather than
// comparison: also trims the result, so a summary with no continuation
// to reveal doesn't show a trailing "…"/"..." that promises more text
// than there is. Only the tail is touched — a mid-sentence ellipsis is
// left as part of the text.
function stripTrailingEllipsisForDisplay(text: string): string {
  return stripTrailingEllipsis(text).trim();
}

// Maps a length in the whitespace-collapsed ("normalized") form of
// `original` back to a character index in `original` itself, so a
// prefix match found on normalized text can be used to slice the
// original (newline-preserving) text at the right place. Each run of
// whitespace in `original` counts as exactly one normalized character,
// matching normalizeForComparison's `\s+` -> " " collapsing.
function mapNormalizedLengthToOriginalIndex(original: string, targetNormalizedLength: number): number {
  let normalizedIndex = 0;
  let i = 0;
  while (i < original.length && normalizedIndex < targetNormalizedLength) {
    if (/\s/.test(original[i])) {
      normalizedIndex += 1;
      while (i < original.length && /\s/.test(original[i])) i += 1;
    } else {
      normalizedIndex += 1;
      i += 1;
    }
  }
  return i;
}

interface ContinuationResult {
  hasContinuation: boolean;
  continuationText?: string;
}

const NO_CONTINUATION: ContinuationResult = { hasContinuation: false };

/**
 * Builds the "続きを見る" continuation text from an item's summary and
 * fullSummary — both built by the backend from the same source text
 * (see dataforseo_client.py's _gather_summary_source_parts /
 * chatgpt_client.py's _summarize), so fullSummary normally starts with
 * summary's text and the goal here is to show only what comes after
 * that shared prefix, not the whole fullSummary again.
 *
 * This is a deliberately simple heuristic (whitespace/ellipsis-
 * tolerant prefix match), not a general text-diff algorithm:
 * - no fullSummary → no continuation.
 * - no summary → fullSummary itself is the continuation (if long enough).
 * - normalized fullSummary/summary are equal → no continuation (nothing new).
 * - normalized fullSummary starts with normalized summary → the
 *   remainder (mapped back into the original, newline-preserving
 *   fullSummary) is the continuation.
 * - otherwise (summary isn't a clean prefix, e.g. a markdown-cleanup
 *   edge case) → fall back to showing fullSummary in full, unless it's
 *   barely longer than summary, in which case treat them as "the same".
 * In every case, a continuation shorter than MIN_CONTINUATION_LENGTH
 * is suppressed rather than shown.
 */
function buildContinuationText(
  summary: string | undefined,
  fullSummary: string | undefined,
): ContinuationResult {
  if (!fullSummary) return NO_CONTINUATION;

  const trimmedFull = fullSummary.trim();
  if (!trimmedFull) return NO_CONTINUATION;

  if (!summary) {
    if (trimmedFull.length < MIN_CONTINUATION_LENGTH) return NO_CONTINUATION;
    return { hasContinuation: true, continuationText: fullSummary };
  }

  const normalizedFull = normalizeForComparison(trimmedFull);
  const normalizedSummary = stripTrailingEllipsis(normalizeForComparison(summary));

  if (normalizedFull === normalizedSummary) return NO_CONTINUATION;

  if (normalizedSummary.length > 0 && normalizedFull.startsWith(normalizedSummary)) {
    const cutIndex = mapNormalizedLengthToOriginalIndex(trimmedFull, normalizedSummary.length);
    const continuation = trimmedFull.slice(cutIndex).trim();
    if (continuation.length < MIN_CONTINUATION_LENGTH) return NO_CONTINUATION;
    return { hasContinuation: true, continuationText: continuation };
  }

  if (normalizedFull.length - normalizedSummary.length < MIN_CONTINUATION_LENGTH) {
    return NO_CONTINUATION;
  }
  return { hasContinuation: true, continuationText: fullSummary };
}

export const OWN_DOMAIN_STATUS_LABELS: Record<"included" | "not_included", string> = {
  included: "自社公式サイトがAI Overviewの参照元に含まれています",
  not_included: "自社公式サイトはAI Overviewの参照元に確認できません",
};

/**
 * Reduces one AIOverviewComparisonItem's optional detail fields
 * (fullSummary/references/referenceSummary/ownDomainReferenced —
 * populated by the DataForSEO provider with all four, or by the
 * ChatGPT/OpenAI provider with fullSummary only; see
 * backend/services/ai_overview_provider.py and chatgpt_provider.py) to
 * exactly what AIOverviewComparisonSection needs to render, so the
 * component itself stays presentation-only. Every field on the input
 * item is optional — an item with none of them (mock data, or an older
 * backend response) yields hasContinuation=false, displaySummary equal
 * to item.summary (minus any trailing "…"/"..."), references=[],
 * referenceSummary=undefined, ownDomainStatus="unjudged", which the
 * section renders as "no change" from the pre-existing summary-only
 * display.
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
      categoryLabel: reference.category ? REFERENCE_CATEGORY_LABELS[reference.category] : undefined,
    }));

  let referenceSummary: AiOverviewReferenceSummaryDisplay | undefined;
  if (item.referenceSummary) {
    const { total, official, thirdParty, categories } = item.referenceSummary;
    const categoryCounts = REFERENCE_CATEGORY_DISPLAY_ORDER.filter(
      (category) => (categories[category] ?? 0) > 0,
    ).map((category) => ({
      label: REFERENCE_CATEGORY_LABELS[category],
      count: categories[category] ?? 0,
    }));
    referenceSummary = { total, official, thirdParty, categoryCounts };
  }

  let ownDomainStatus: OwnDomainReferenceStatus = "unjudged";
  if (item.ownDomainReferenced === true) ownDomainStatus = "included";
  else if (item.ownDomainReferenced === false) ownDomainStatus = "not_included";

  const { hasContinuation, continuationText } = buildContinuationText(item.summary, item.fullSummary);
  const displaySummary =
    !hasContinuation && item.summary
      ? stripTrailingEllipsisForDisplay(item.summary)
      : item.summary;

  return {
    hasContinuation,
    continuationText,
    displaySummary,
    references,
    referenceSummary,
    ownDomainStatus,
  };
}
