// Types, display text, and view-state resolution for the minimal
// analysis history list UI (docs/21_analysis_history_ui_design.md).
//
// Display strings are kept as plain exported constants/functions —
// rather than inline JSX text — so they can be unit-tested without a
// React component-rendering library, which this project doesn't have
// (see app/lib/staging-banner.ts for the same pattern).

import {
  parseAnalysisRunComparisonResponse,
  parseAnalysisRunDetailResponse,
  parseAnalysisRunListResponse,
} from "./analysis-history-schema";
import { parseAnalysisResult } from "./analysis-result-schema";
import type { AnalysisResult, CooccurrenceKeyword } from "./types";

/** One row of GET /analysis-runs's `items` — mirrors
 * backend/models.py's AnalysisRunListItem. Deliberately excludes
 * result/resultJson (see docs/20_analysis_history_read_api_design.md
 * "5. GET /analysis-runs の設計案"「返さないもの」) — the list view
 * never needs to know about them.
 */
export type AnalysisRunListItem = {
  id: string;
  brandName: string;
  canonicalDomain?: string;
  status: string;
  visibilityScore?: number;
  sourceSummary?: Record<string, number>;
  startedAt?: string;
  completedAt?: string;
  createdAt?: string;
};

export type AnalysisRunListResponse = {
  items: AnalysisRunListItem[];
  limit: number;
  offset: number;
  total: number | null;
};

export const HISTORY_PAGE_TITLE = "分析履歴";
export const HISTORY_PAGE_DESCRIPTION =
  "保存済みの分析結果を一覧で確認できます。";
export const HISTORY_EMPTY_STATE_TEXT = "保存済みの分析履歴はまだありません。";
export const HISTORY_LOADING_TEXT = "分析履歴を読み込んでいます...";

// Shown when GET /analysis-runs returns 503 — this means "history read
// is disabled/unconfigured", not "zero saved analyses" (see
// docs/21_analysis_history_ui_design.md "9. READ_HISTORY_ENABLED=false
// 時の表示方針"). The detail line names READ_HISTORY_ENABLED
// explicitly — acceptable for this initial verification-oriented UI
// per that section's recommendation ("初期の検証UIでは...説明を出して
// よい"); a production-facing UI should trim this down.
export const HISTORY_DISABLED_MESSAGE = "分析履歴の読み込みは現在無効です。";
export const HISTORY_DISABLED_DETAIL =
  "管理者が履歴read APIを有効にすると、保存済み履歴を表示できます。READ_HISTORY_ENABLED が無効、またはDB接続情報が未設定の可能性があります。";

export const HISTORY_GENERIC_ERROR_MESSAGE =
  "分析履歴を読み込めませんでした。時間をおいて再度お試しください。";

// Shown when the Python API returns 403 — the HISTORY_READ_TOKEN gate
// rejected the request (see docs/24_auth_rls_history_access_design.md
// "7. backend APIでのアクセス制御案"). Reused for both the list and
// detail pages, same as HISTORY_DISABLED_MESSAGE above.
export const HISTORY_FORBIDDEN_MESSAGE = "分析履歴を表示する権限がありません。";

// Header this app's own /api/analysis-runs* Route Handlers attach when
// proxying to the Python API, from the server-side-only
// process.env.HISTORY_READ_TOKEN — never sent to or read from the
// browser (see app/api/analysis-runs/route.ts /
// app/api/analysis-runs/[id]/route.ts). Must match backend/main.py's
// HISTORY_READ_TOKEN_HEADER exactly.
export const HISTORY_READ_TOKEN_HEADER = "X-History-Read-Token";

const STATUS_LABELS: Record<string, string> = {
  completed: "完了",
  partial: "一部完了",
  failed: "失敗",
  running: "実行中",
  queued: "待機中",
};

export function getStatusLabel(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

/** Renders a source-type breakdown as e.g. "web_fetch: 1 / common_crawl: 3".
 * Intentionally minimal — not the main focus of this task (see
 * docs/21_analysis_history_ui_design.md "5. sourceSummary の表示").
 */
export function formatSourceSummary(
  sourceSummary: Record<string, number> | undefined,
): string | undefined {
  if (!sourceSummary) return undefined;
  const entries = Object.entries(sourceSummary);
  if (entries.length === 0) return undefined;
  return entries.map(([sourceType, count]) => `${sourceType}: ${count}`).join(" / ");
}

export type AnalysisRunListItemDisplay = {
  brandNameLabel: string;
  canonicalDomainLabel?: string;
  statusLabel: string;
  visibilityScoreLabel?: string;
  sourceSummaryLabel?: string;
  startedAtLabel: string;
};

export function formatAnalysisRunListItem(
  item: AnalysisRunListItem,
): AnalysisRunListItemDisplay {
  return {
    brandNameLabel: item.brandName,
    canonicalDomainLabel: item.canonicalDomain,
    statusLabel: getStatusLabel(item.status),
    visibilityScoreLabel:
      typeof item.visibilityScore === "number"
        ? `可視性スコア ${item.visibilityScore}`
        : undefined,
    sourceSummaryLabel: formatSourceSummary(item.sourceSummary),
    startedAtLabel: item.startedAt ?? item.createdAt ?? "実行日時不明",
  };
}

export type HistoryViewState =
  | { kind: "loading" }
  | { kind: "disabled"; message: string; detail: string }
  | { kind: "forbidden"; message: string }
  | { kind: "error"; message: string }
  | { kind: "empty" }
  | { kind: "items"; items: AnalysisRunListItem[] };

/**
 * Turns a fetch() Response (or null, on a network-level failure) from
 * /api/analysis-runs into a view state the page can render directly.
 * Exported as a pure-ish function (only side effect: reading the
 * response body) so it's unit-testable without rendering any JSX —
 * see app/lib/analysis-history.test.ts.
 */
export async function resolveHistoryFetchOutcome(
  response: Response | null,
): Promise<HistoryViewState> {
  if (!response) {
    return { kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 503) {
    return {
      kind: "disabled",
      message: HISTORY_DISABLED_MESSAGE,
      detail: HISTORY_DISABLED_DETAIL,
    };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisRunListResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: HISTORY_GENERIC_ERROR_MESSAGE };
  }

  if (parsed.data.items.length === 0) {
    return { kind: "empty" };
  }

  return { kind: "items", items: parsed.data.items };
}

/** Link text for a list row's "view detail" link — replaces the
 * earlier "詳細は後続対応" placeholder now that
 * docs/22_analysis_history_detail_ui_design.md's detail page is
 * implemented (see app/history/page.tsx / app/history/[id]/page.tsx).
 */
export const HISTORY_LIST_DETAIL_LINK_TEXT = "詳細を見る";

/** Builds the /history/{id} path for a list row's detail link.
 * `encodeURIComponent` guards against an id containing characters
 * that would otherwise be interpreted as path segments. */
export function buildHistoryDetailPath(id: string): string {
  return `/history/${encodeURIComponent(id)}`;
}

// --- Detail page (GET /analysis-runs/{id}, docs/22_analysis_history_detail_ui_design.md) ---

export const HISTORY_DETAIL_PAGE_TITLE = "分析履歴の詳細";
export const HISTORY_DETAIL_BACK_LINK_TEXT = "分析履歴一覧へ戻る";

export const HISTORY_DETAIL_NOT_FOUND_MESSAGE =
  "指定された分析履歴が見つかりません。";

// Shown when the saved result_json no longer matches the current
// AnalysisResult shape (see app/lib/analysis-result-schema.ts) — a
// distinct outcome from a network/schema-envelope failure, since the
// envelope itself (brand/run info) parsed fine (see
// docs/22_analysis_history_detail_ui_design.md "9. 保存済み
// result_jsonの扱い").
export const HISTORY_DETAIL_INCOMPATIBLE_MESSAGE =
  "保存済み分析結果の形式が現在の表示形式と一致しません。";

export const HISTORY_DETAIL_GENERIC_ERROR_MESSAGE =
  "分析履歴の詳細を読み込めませんでした。時間をおいて再度お試しください。";

/** One row of GET /analysis-runs/{id}'s `brand` — mirrors
 * backend/models.py's AnalysisRunBrand. */
export type AnalysisRunBrand = {
  id: string;
  name: string;
  canonicalDomain?: string;
};

/** GET /analysis-runs/{id}'s `run` — mirrors backend/models.py's
 * AnalysisRunInfo. Unlike AnalysisRunListItem, `inputSnapshot` is
 * always present (it's a required field on the backend model) and
 * there is no `createdAt` here. */
export type AnalysisRunInfo = {
  status: string;
  inputSnapshot: Record<string, unknown>;
  sourceSummary?: Record<string, number>;
  startedAt?: string;
  completedAt?: string;
};

/** GET /analysis-runs/{id} — mirrors backend/models.py's
 * AnalysisRunDetailResponse. `result` is kept as a loose
 * `Record<string, unknown>` (the raw, saved result_json) rather than
 * `AnalysisResult` — see app/lib/analysis-history-schema.ts's module
 * doc for why it's validated separately. */
export type AnalysisRunDetailResponse = {
  id: string;
  brand: AnalysisRunBrand;
  run: AnalysisRunInfo;
  result: Record<string, unknown>;
  meta?: Record<string, unknown>;
};

export type AnalysisRunDetailBasicInfoDisplay = {
  brandNameLabel: string;
  canonicalDomainLabel?: string;
  statusLabel: string;
  startedAtLabel: string;
  sourceSummaryLabel?: string;
  visibilityScoreLabel?: string;
};

/** Formats the "basic info" shown above the reused AnalysisDashboard —
 * sourced from `brand`/`run` (always available once the envelope
 * parses) plus `result.summary.visibilityScore` when `result` itself
 * parsed as a valid AnalysisResult (omitted otherwise, e.g. in the
 * "incompatible" outcome). */
export function formatAnalysisRunDetailBasicInfo(
  detail: AnalysisRunDetailResponse,
  result?: AnalysisResult,
): AnalysisRunDetailBasicInfoDisplay {
  return {
    brandNameLabel: detail.brand.name,
    canonicalDomainLabel: detail.brand.canonicalDomain,
    statusLabel: getStatusLabel(detail.run.status),
    startedAtLabel: detail.run.startedAt ?? "実行日時不明",
    sourceSummaryLabel: formatSourceSummary(detail.run.sourceSummary),
    visibilityScoreLabel:
      result && typeof result.summary.visibilityScore === "number"
        ? `可視性スコア ${result.summary.visibilityScore}`
        : undefined,
  };
}

export type AnalysisRunDetailViewState =
  | { kind: "loading" }
  | { kind: "disabled"; message: string; detail: string }
  | { kind: "forbidden"; message: string }
  | { kind: "notFound"; message: string }
  | { kind: "incompatible"; message: string }
  | { kind: "error"; message: string }
  | { kind: "success"; detail: AnalysisRunDetailResponse; result: AnalysisResult };

/**
 * Turns a fetch() Response (or null, on a network-level failure) from
 * /api/analysis-runs/{id} into a view state the detail page can render
 * directly — mirrors resolveHistoryFetchOutcome() above. Distinguishes
 * "not found" (404) from "disabled" (503) from a saved result that no
 * longer validates as the current AnalysisResult shape ("incompatible")
 * from any other failure ("error").
 */
export async function resolveHistoryDetailFetchOutcome(
  response: Response | null,
): Promise<AnalysisRunDetailViewState> {
  if (!response) {
    return { kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 503) {
    return {
      kind: "disabled",
      message: HISTORY_DISABLED_MESSAGE,
      detail: HISTORY_DISABLED_DETAIL,
    };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE };
  }

  if (response.status === 404) {
    return { kind: "notFound", message: HISTORY_DETAIL_NOT_FOUND_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisRunDetailResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: HISTORY_DETAIL_GENERIC_ERROR_MESSAGE };
  }

  const resultParsed = parseAnalysisResult(parsed.data.result);
  if (!resultParsed.success) {
    return { kind: "incompatible", message: HISTORY_DETAIL_INCOMPATIBLE_MESSAGE };
  }

  return { kind: "success", detail: parsed.data, result: resultParsed.data };
}

// --- Post-analyze "open in history" link (analysis result screen,
// docs/23_analysis_run_id_and_post_analyze_link_design.md "8. 分析結果
// 画面のリンク表示方針") ---

export const POST_ANALYZE_HISTORY_LINK_TEXT = "保存済み履歴で開く";
export const POST_ANALYZE_HISTORY_LINK_HELPER_TEXT =
  "この分析結果は履歴に保存されています。";

export type PostAnalyzeHistoryLink = {
  path: string;
};

/**
 * Decides whether the analysis result screen should show an "open in
 * history" link, from AnalysisResult.analysisRunId alone. Returns null
 * for null/undefined/empty-string analysisRunId (DB save disabled,
 * unconfigured, or failed — see docs/23_analysis_run_id_and_post_analyze_link_design.md
 * "6. DB保存成功・失敗時の扱い") — the screen shows nothing in that
 * case, not a warning (per that doc's "3. analysisRunIdがない場合").
 *
 * Deliberately does not know about READ_HISTORY_ENABLED — when it's
 * false, the link still renders but the linked /history/[id] page
 * shows its own existing disabled message (see that doc's "9.
 * READ_HISTORY_ENABLED=false時の扱い").
 */
export function resolvePostAnalyzeHistoryLink(
  analysisRunId: string | null | undefined,
): PostAnalyzeHistoryLink | null {
  if (!analysisRunId) {
    return null;
  }

  return { path: buildHistoryDetailPath(analysisRunId) };
}

// --- History comparison (GET /analysis-runs/{id}/comparison,
// docs/25_analysis_history_comparison_design.md) — a small "前回比較"
// section on the existing /history/[id] page, not a new page. Mirrors
// backend/models.py's AnalysisRunComparison* models exactly.

/** One side (`current`/`previous`) of the comparison response. */
export type AnalysisRunComparisonRunSummary = {
  id: string;
  startedAt: string | null;
  visibilityScore: number | null;
};

export type CooccurrenceComparisonNewTerm = {
  term: string;
  rank: number;
  score: number;
};

export type CooccurrenceComparisonRemovedTerm = {
  term: string;
  rank: number;
  score: number;
};

/** `rankDelta`/`scoreDelta` are current-minus-previous — a negative
 * `rankDelta` means the term's rank *improved* (see backend/models.py's
 * CooccurrenceComparisonChangedTerm docstring). */
export type CooccurrenceComparisonChangedTerm = {
  term: string;
  currentRank: number;
  previousRank: number;
  rankDelta: number;
  currentScore: number;
  previousScore: number;
  scoreDelta: number;
};

export type AnalysisRunComparisonDiff = {
  visibilityScore: {
    current: number | null;
    previous: number | null;
    delta: number | null;
  };
  cooccurrence: {
    topN: number;
    newTerms: CooccurrenceComparisonNewTerm[];
    removedTerms: CooccurrenceComparisonRemovedTerm[];
    changedTerms: CooccurrenceComparisonChangedTerm[];
  };
  improvements: {
    currentCount: number;
    previousCount: number;
    delta: number;
  };
};

/** GET /analysis-runs/{id}/comparison — mirrors backend/models.py's
 * AnalysisRunComparisonResponse. `previous`/`diff` are both null when
 * the same brand has no earlier run yet; `warnings` explains why in
 * that case (and separately flags provider-mode mismatches /
 * incompatible saved results when a comparison was computed). */
export type AnalysisRunComparisonResponse = {
  current: AnalysisRunComparisonRunSummary;
  previous: AnalysisRunComparisonRunSummary | null;
  diff: AnalysisRunComparisonDiff | null;
  warnings: string[];
};

/** Narrows AnalysisRunComparisonResponse for the "success" outcome
 * below, where `previous`/`diff` are known to be non-null (that case
 * is resolved as "noPrevious" instead — see
 * resolveHistoryComparisonFetchOutcome()) — lets callers read
 * `comparison.diff.*` without a redundant null check. */
export type ResolvedAnalysisRunComparison = AnalysisRunComparisonResponse & {
  previous: AnalysisRunComparisonRunSummary;
  diff: AnalysisRunComparisonDiff;
};

export const HISTORY_COMPARISON_SECTION_TITLE = "前回比較";
export const HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL = "可視性スコア";
export const HISTORY_COMPARISON_COOCCURRENCE_LABEL = "共起語の変化";
export const HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL = "新規";
export const HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL = "消失";
export const HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL = "変化";
export const HISTORY_COMPARISON_IMPROVEMENTS_LABEL = "改善提案数";

export const HISTORY_COMPARISON_NOT_FOUND_MESSAGE =
  "比較対象の分析履歴が見つかりません。";
export const HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE =
  "比較できる過去履歴がまだありません。";
export const HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE =
  "前回比較を読み込めませんでした。";

export type HistoryComparisonViewState =
  | { kind: "loading" }
  | { kind: "disabled"; message: string }
  | { kind: "forbidden"; message: string }
  | { kind: "notFound"; message: string }
  | { kind: "noPrevious"; message: string }
  | { kind: "error"; message: string }
  | { kind: "success"; comparison: ResolvedAnalysisRunComparison };

/**
 * Turns a fetch() Response (or null, on a network-level failure) from
 * /api/analysis-runs/{id}/comparison into a view state the "前回比較"
 * section can render directly — mirrors resolveHistoryDetailFetchOutcome().
 * A 200 response with `previous`/`diff` both null (the same brand has
 * no earlier run yet) is deliberately resolved as "noPrevious" rather
 * than "success", since there is nothing to diff.
 *
 * Failures here are meant to degrade gracefully: the caller (the
 * /history/[id] page) must keep showing the rest of the history detail
 * even when this resolves to "disabled"/"forbidden"/"notFound"/"error"
 * (see docs/25_analysis_history_comparison_design.md "14. エラー・
 * データ不足時の表示方針").
 */
export async function resolveHistoryComparisonFetchOutcome(
  response: Response | null,
): Promise<HistoryComparisonViewState> {
  if (!response) {
    return { kind: "error", message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE };
  }

  if (response.status === 503) {
    return { kind: "disabled", message: HISTORY_DISABLED_MESSAGE };
  }

  if (response.status === 403) {
    return { kind: "forbidden", message: HISTORY_FORBIDDEN_MESSAGE };
  }

  if (response.status === 404) {
    return { kind: "notFound", message: HISTORY_COMPARISON_NOT_FOUND_MESSAGE };
  }

  if (!response.ok) {
    return { kind: "error", message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE };
  }

  const json = await response.json().catch(() => null);
  const parsed = parseAnalysisRunComparisonResponse(json);
  if (!parsed.success) {
    return { kind: "error", message: HISTORY_COMPARISON_GENERIC_ERROR_MESSAGE };
  }

  if (parsed.data.previous === null || parsed.data.diff === null) {
    return { kind: "noPrevious", message: HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE };
  }

  return {
    kind: "success",
    comparison: parsed.data as ResolvedAnalysisRunComparison,
  };
}

/** Formats a delta as "+5" / "-7" / "±0" — shared by every "before →
 * after（delta）" label below. */
export function formatSignedDelta(delta: number): string {
  if (delta > 0) return `+${delta}`;
  if (delta < 0) return `${delta}`;
  return "±0";
}

/** "86 → 91（+5）" — null when either side is missing (the caller
 * shows a fallback message in that case; see
 * docs/25_analysis_history_comparison_design.md "10. スコア比較の扱い"). */
export function formatComparisonVisibilityScoreLabel(
  diff: AnalysisRunComparisonDiff["visibilityScore"],
): string | null {
  if (diff.current === null || diff.previous === null || diff.delta === null) {
    return null;
  }
  return `${diff.previous} → ${diff.current}（${formatSignedDelta(diff.delta)}）`;
}

/** "3 → 4（+1）" */
export function formatComparisonImprovementsLabel(
  diff: AnalysisRunComparisonDiff["improvements"],
): string {
  return `${diff.previousCount} → ${diff.currentCount}（${formatSignedDelta(diff.delta)}）`;
}

export function formatCooccurrenceNewTermLabel(
  term: CooccurrenceComparisonNewTerm,
): string {
  return `${term.term}（${term.rank}位）`;
}

export function formatCooccurrenceRemovedTermLabel(
  term: CooccurrenceComparisonRemovedTerm,
): string {
  return `${term.term}（${term.rank}位）`;
}

export function formatCooccurrenceChangedTermLabel(
  term: CooccurrenceComparisonChangedTerm,
): string {
  return `${term.term}（${term.previousRank}位→${term.currentRank}位、スコア${term.previousScore}→${term.currentScore}）`;
}

/** Caps a comparison term list to a small number of entries for
 * display — see docs/25_analysis_history_comparison_design.md "7. UI
 * 設計案"「初期は全部を詳細テーブルにしなくてよい。上位数件のリスト
 * でよい。」 */
export const HISTORY_COMPARISON_TERM_DISPLAY_LIMIT = 5;

export function limitComparisonTerms<T>(
  terms: T[],
  limit: number = HISTORY_COMPARISON_TERM_DISPLAY_LIMIT,
): T[] {
  return terms.slice(0, limit);
}

// --- Report page (/history/[id]/report, docs/26_report_output_design.md)
// — a print-oriented HTML page built from the same two endpoints as
// /history/[id] (GET /analysis-runs/{id} and its /comparison), reusing
// resolveHistoryDetailFetchOutcome()/resolveHistoryComparisonFetchOutcome()
// above rather than adding any new API. No backend change, no new
// frontend proxy route — see that doc's "11. frontend実装方針".

export const REPORT_PAGE_TITLE = "分析レポート";
export const REPORT_LINK_TEXT = "レポート表示";
export const REPORT_BACK_TO_DETAIL_LINK_TEXT = "履歴詳細へ戻る";

export const REPORT_SECTION_TITLES = {
  summary: "サマリー",
  webContext: "Web上の文脈",
  aiObservation: "AI回答側の観測",
  comparison: "前回比較",
  improvements: "改善提案",
  notes: "注意事項",
} as const;

/** Builds the /history/{id}/report path for the "レポート表示" link on
 * the history detail page. Mirrors buildHistoryDetailPath() above. */
export function buildHistoryReportPath(id: string): string {
  return `/history/${encodeURIComponent(id)}/report`;
}

// Shown instead of the whole report when the history detail itself
// couldn't be fetched (see docs/26_report_output_design.md "15. エラー・
// データ不足時の表示方針"「履歴詳細が取得できない場合」) — a report
// can't be built at all without its underlying detail. The more
// specific forbidden/disabled reasons (403/503) are shown as-is since
// they're already the exact wording that section calls for; every
// other failure (not found / incompatible saved result / network
// error) falls back to this generic message rather than surfacing
// detail-page wording that doesn't apply to a report ("この履歴は見
// つかりません" etc. would be confusing framed as a report).
export const REPORT_DETAIL_UNAVAILABLE_MESSAGE = "レポートを表示できません。";

/** Resolves the message to show in place of the whole report when the
 * underlying history detail fetch didn't succeed. Only meant to be
 * called for a non-loading, non-success AnalysisRunDetailViewState. */
export function resolveReportDetailMessage(
  view: Exclude<AnalysisRunDetailViewState, { kind: "loading" } | { kind: "success" }>,
): string {
  if (view.kind === "forbidden" || view.kind === "disabled") {
    return view.message;
  }
  return REPORT_DETAIL_UNAVAILABLE_MESSAGE;
}

// Shown for the report's "前回比較" section specifically (distinct from
// REPORT_DETAIL_UNAVAILABLE_MESSAGE above) when the comparison fetch
// itself failed for a reason other than "no previous run yet" — see
// docs/26_report_output_design.md "15. エラー・データ不足時の表示方針"
// 「比較データが取得できない場合」. A comparison failure never removes
// the rest of the report (see docs/25_analysis_history_comparison_design.md
// "14. エラー・データ不足時の表示方針", the same policy this report page
// follows).
export const REPORT_COMPARISON_UNAVAILABLE_MESSAGE = "前回比較は表示できません。";

/** Resolves the message to show in the report's "前回比較" section when
 * the comparison fetch didn't resolve to "success". Distinguishes
 * "no previous run yet" (its own exact wording, HISTORY_COMPARISON_NO_PREVIOUS_MESSAGE)
 * from every other failure (REPORT_COMPARISON_UNAVAILABLE_MESSAGE),
 * while still surfacing the shared 403/503 wording as-is. Only meant
 * to be called for a non-loading, non-success HistoryComparisonViewState. */
export function resolveReportComparisonMessage(
  view: Exclude<HistoryComparisonViewState, { kind: "loading" } | { kind: "success" }>,
): string {
  if (view.kind === "forbidden" || view.kind === "disabled" || view.kind === "noPrevious") {
    return view.message;
  }
  return REPORT_COMPARISON_UNAVAILABLE_MESSAGE;
}

/** How many top cooccurrenceRanking entries the report's "Web上の文脈"
 * section shows — kept small so the printed page stays readable (see
 * docs/26_report_output_design.md "7. レポートに含める項目"). */
export const REPORT_COOCCURRENCE_DISPLAY_LIMIT = 10;

export function limitReportCooccurrenceTerms(
  terms: CooccurrenceKeyword[],
  limit: number = REPORT_COOCCURRENCE_DISPLAY_LIMIT,
): CooccurrenceKeyword[] {
  return terms.slice(0, limit);
}

// Shown in the report's "AI回答側の観測" section when
// aiOverviewComparison is empty — covers both AI Overview mode being
// off/unavailable and ChatGPT observation mode being off, without
// trying to distinguish which (see docs/26_report_output_design.md
// "15. エラー・データ不足時の表示方針" — this report keeps the two
// specific messages listed there merged into one, per that doc's
// "ただし、初期実装なので過度に凝らない" framing for this task).
export const REPORT_AI_OVERVIEW_EMPTY_MESSAGE =
  "AI Overview / ChatGPT観測データはありません。";

// Fixed disclaimer text for the report's "注意事項" section (see
// docs/26_report_output_design.md "9. レポート構成案"「8. 注意事項」).
// Kept as plain data here (not JSX) so it's covered by the same
// unit-testing approach as the rest of this file.
export const REPORT_NOTES: string[] = [
  "本レポートは公開Web情報をもとに、生成AIにどのように認知されやすいかを推定したものであり、特定のAIモデルの学習内容を完全に再現するものではありません。",
  "実際の生成AIの内部的な学習状態・重み付けを保証するものではありません。",
  "前回比較は、AI Overview取得モード等のprovider設定が前回と異なる場合、単純な比較には注意が必要です。",
];

export const REPORT_PRINT_BUTTON_LABEL = "PDF保存 / 印刷";

/** Triggers the browser's native print dialog — the only way this
 * initial report page produces a PDF (ブラウザの印刷機能でPDF保存、see
 * docs/26_report_output_design.md "6. 初期出力形式"). No server-side
 * PDF generation, no new backend endpoint. Wrapped as its own function
 * so the "print" action is unit-testable without a component-rendering
 * library — see app/components/ReportPrintButton.tsx for the button
 * that calls it. */
export function printReport(): void {
  window.print();
}
