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

/**
 * A short "分析ソース内訳" line combining how many Webページ Documents
 * were fetched via `urls` (meta.urlFetchResults, reusing the same
 * success-count logic as getUrlFetchSummary above) with how many
 * Common Crawl補完 Documents were added (meta.commonCrawlProvider,
 * only when status is "real" — an "off"/"unavailable" Common Crawl
 * result contributed zero Documents, and its own reason is already
 * shown separately by getCommonCrawlProviderDisplay, so it's
 * deliberately not repeated here), e.g. "Webページ 1件 / Common
 * Crawl補完 3件". Added so a request that combines both sources makes
 * it obvious at a glance how many Documents came from each, rather
 * than requiring the reader to mentally combine two separate status
 * lines (see docs/13_common_crawl_mvp_design.md's "分析ソース内訳").
 *
 * Returns null when there's nothing to show (no urlFetchResults and no
 * successful Common Crawl addition) — e.g. development_sample/
 * user_provided-only analyses, matching this project's convention of
 * only showing a status line when there's something worth reporting.
 * Never reads/renders HTML or WARC body text — meta.commonCrawlProvider
 * has no field for either.
 */
export function getAnalysisSourceBreakdownDisplay(meta: AnalysisMeta): string | null {
  const parts: string[] = [];

  if (meta.urlFetchResults && meta.urlFetchResults.length > 0) {
    const successCount = meta.urlFetchResults.filter((r) => r.success).length;
    parts.push(`Webページ ${successCount}件`);
  }

  if (meta.commonCrawlProvider && meta.commonCrawlProvider.status === "real") {
    parts.push(`Common Crawl補完 ${meta.commonCrawlProvider.documentCount ?? 0}件`);
  }

  if (parts.length === 0) return null;

  return parts.join(" / ");
}

export interface CommonCrawlProviderDisplay {
  // A single line matching the display examples in the task this was
  // built for — e.g. "Common Crawl補完: 未使用" /
  // "Common Crawl補完: 取得済み（1件）" /
  // "Common Crawl補完: 補完データ未取得". Never includes HTML/WARC
  // body text — meta.commonCrawlProvider has no field for either (see
  // backend/models.py's CommonCrawlProviderInfo).
  summary: string;
  // domain/crawlIndex on a "real" success, or a short, non-technical
  // reason on an "unavailable" result (see
  // classifyCommonCrawlUnavailableReason below) — never WARC-level
  // metadata (filename/offset/length are not part of
  // CommonCrawlProviderInfo at all) and never the backend's raw
  // `reason` string verbatim.
  detail?: string;
}

// Matched in order against meta.commonCrawlProvider.reason (a
// developer-facing string from backend/services/common_crawl_index.py /
// common_crawl_warc.py / common_crawl_document_provider.py /
// backend/main.py — see the grep of every `reason=`/`reason=f"` literal
// in those files this list was built from) to classify an
// "unavailable" result into one of a handful of short, non-technical
// phrases — added 2026-07-28 (style/common-crawl-status-display,
// hardened 2026-07-28 fix/common-crawl-status-japanese-reasons) so a
// non-engineer reader is never shown a raw English string like "Common
// Crawl domain could not be determined from commonCrawlDomain or
// urls." First match wins; order matters because some backend reason
// strings could otherwise match more than one bucket (e.g. "Common
// Crawl domain is empty or not a valid hostname." contains "empty",
// which would otherwise be mistaken for the "0 results" bucket below
// it). Patterns are intentionally broader than the exact strings the
// backend happens to emit today (e.g. matching bare "hostname" rather
// than only the full current sentence), so a minor future wording
// change in the backend's `reason` text doesn't silently fall through
// to the generic fallback.
const _COMMON_CRAWL_UNAVAILABLE_REASON_RULES: { pattern: RegExp; message: string }[] = [
  // Domain couldn't be determined/validated — checked first so its use
  // of the word "empty" doesn't fall through to the no-candidates rule.
  {
    pattern: /could not be determined|commoncrawldomain or urls|domain missing|hostname/i,
    message: "補完対象ドメインを特定できませんでした",
  },
  // Common Crawl itself is disabled/off — in practice this reason only
  // ever accompanies status="off" (handled by its own switch case
  // below, never reaching this classifier), but matched here too as a
  // defensive fallback in case that invariant ever changes.
  {
    pattern: /disabled|COMMON_CRAWL_ENABLED/i,
    message: "Common Crawl補完は未使用です",
  },
  // Network/timeout/HTTP/parse failures, and "found candidates but
  // none could be fetched" (matched via "fetch").
  {
    pattern: /timeout|network|request failed|failed due to|http \d|not valid json|was not a list|no recognizable crawl index|fetch/i,
    message: "Common Crawl補完の取得処理が完了しませんでした",
  },
  // No candidates/results at all.
  {
    pattern: /was empty|no candidates|0 results/i,
    message: "補完対象ページが見つかりませんでした",
  },
];

/**
 * Reduces a backend `reason` string (meant for developers/logs, not
 * end users) down to one of a handful of short, non-technical phrases
 * a non-engineer can understand — never the raw string itself. Falls
 * back to a generic "取得できませんでした" phrase for any reason that
 * doesn't match a known pattern (including a missing/blank reason),
 * so a new backend failure mode never leaks raw text into the UI
 * before this list is updated to recognize it.
 */
function classifyCommonCrawlUnavailableReason(reason: string | undefined): string {
  const trimmed = reason?.trim();
  if (trimmed) {
    for (const rule of _COMMON_CRAWL_UNAVAILABLE_REASON_RULES) {
      if (rule.pattern.test(trimmed)) return rule.message;
    }
  }
  return "補完データを取得できませんでした";
}

/**
 * Describes whether the Common Crawl "補完" (supplementary) flow added
 * a Document this request, for a small status line near the
 * co-occurrence section (see backend/main.py's
 * _build_common_crawl_documents() and
 * docs/13_common_crawl_mvp_design.md). Returns null when
 * meta.commonCrawlProvider isn't present (e.g. the client-side dummy
 * fallback in app/lib/dummy-data.ts, or an older backend response that
 * predates this field).
 */
export function getCommonCrawlProviderDisplay(
  meta: AnalysisMeta,
): CommonCrawlProviderDisplay | null {
  const provider = meta.commonCrawlProvider;
  if (!provider) return null;

  switch (provider.status) {
    case "off":
      return { summary: "Common Crawl補完: 未使用" };

    case "real": {
      const detailParts = [
        provider.domain ? `対象ドメイン: ${provider.domain}` : null,
        provider.crawlIndex ? `クロールIndex: ${provider.crawlIndex}` : null,
      ].filter((part): part is string => part !== null);
      return {
        summary: `Common Crawl補完: 取得済み（${provider.documentCount ?? 0}件）`,
        detail: detailParts.length > 0 ? detailParts.join(" / ") : undefined,
      };
    }

    case "unavailable":
    default:
      return {
        summary: "Common Crawl補完: 補完データ未取得",
        detail: `理由: ${classifyCommonCrawlUnavailableReason(provider.reason)}`,
      };
  }
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

// At or below this length, fullSummary is shown in full up front instead
// of summary + a "続きを見る" toggle — short/medium-length answers (the
// common case for the ChatGPT observation) read more naturally as one
// paragraph than as a sentence cut mid-way with the rest hidden behind a
// toggle. Only fullSummary longer than this falls through to the
// existing summary + continuation-toggle behavior below. 600 is a rough
// "still reads as one short paragraph" cutoff, not derived from any
// particular backend truncation length.
const INLINE_FULL_SUMMARY_MAX_LENGTH = 600;

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
 * component itself stays presentation-only.
 *
 * When fullSummary is short enough to read as one paragraph
 * (<= INLINE_FULL_SUMMARY_MAX_LENGTH), it's shown in full as
 * displaySummary with no "続きを見る" toggle at all — this avoids a
 * short answer reading as a sentence cut off mid-way with the rest
 * hidden behind a toggle. Only a longer fullSummary falls through to
 * the summary + continuation-toggle behavior below.
 *
 * Every field on the input item is optional — an item with none of
 * them (mock data, or an older backend response) yields
 * hasContinuation=false, displaySummary equal
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

  const isShortFullSummary =
    item.fullSummary !== undefined && item.fullSummary.length <= INLINE_FULL_SUMMARY_MAX_LENGTH;

  let hasContinuation: boolean;
  let continuationText: string | undefined;
  let displaySummary: string;

  if (isShortFullSummary) {
    // Short enough to read naturally as one paragraph — show it in full
    // right away rather than truncating to summary + a toggle that would
    // otherwise cut the sentence mid-way (see INLINE_FULL_SUMMARY_MAX_LENGTH).
    hasContinuation = false;
    continuationText = undefined;
    displaySummary = item.fullSummary as string;
  } else {
    ({ hasContinuation, continuationText } = buildContinuationText(item.summary, item.fullSummary));
    displaySummary =
      !hasContinuation && item.summary
        ? stripTrailingEllipsisForDisplay(item.summary)
        : item.summary;
  }

  return {
    hasContinuation,
    continuationText,
    displaySummary,
    references,
    referenceSummary,
    ownDomainStatus,
  };
}
