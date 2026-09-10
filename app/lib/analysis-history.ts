// Types, display text, and view-state resolution for the minimal
// analysis history list UI (docs/21_analysis_history_ui_design.md).
//
// Display strings are kept as plain exported constants/functions —
// rather than inline JSX text — so they can be unit-tested without a
// React component-rendering library, which this project doesn't have
// (see app/lib/staging-banner.ts for the same pattern).

import {
  parseAnalysisRunDetailResponse,
  parseAnalysisRunListResponse,
} from "./analysis-history-schema";
import { parseAnalysisResult } from "./analysis-result-schema";
import type { AnalysisResult } from "./types";

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
