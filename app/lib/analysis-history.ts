// Types, display text, and view-state resolution for the minimal
// analysis history list UI (docs/21_analysis_history_ui_design.md).
//
// Display strings are kept as plain exported constants/functions —
// rather than inline JSX text — so they can be unit-tested without a
// React component-rendering library, which this project doesn't have
// (see app/lib/staging-banner.ts for the same pattern).

import { parseAnalysisRunListResponse } from "./analysis-history-schema";

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
