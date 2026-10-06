"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AnalysisDashboard from "../../components/AnalysisDashboard";
import AppHeader from "../../components/AppHeader";
import Breadcrumb from "../../components/Breadcrumb";
import { REPORT_LINK_BUTTON_CLASSNAME } from "../../lib/link-button-styles";
import {
  GEMINI_RERUN_CONFIRM_MESSAGE,
  GEMINI_RERUN_SUCCESS_MESSAGE,
  HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL,
  HISTORY_COMPARISON_IMPROVEMENTS_LABEL,
  HISTORY_COMPARISON_INTRO_TEXT,
  HISTORY_COMPARISON_SECTION_TITLE,
  HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL,
  HISTORY_DETAIL_OFFICIAL_NOTE,
  HISTORY_DETAIL_PAGE_TITLE,
  HISTORY_IMPORTANT_BADGE_LABEL,
  HISTORY_LOADING_TEXT,
  REPORT_LINK_TEXT,
  buildHistoryReportPath,
  formatAnalysisRunDetailBasicInfo,
  formatComparisonImprovementsLabel,
  formatComparisonVisibilityScoreLabel,
  formatCooccurrenceChangedTermLabel,
  formatCooccurrenceNewTermLabel,
  formatCooccurrenceRemovedTermLabel,
  getImportantToggleLabel,
  limitComparisonTerms,
  resolveGeminiRerunOutcome,
  resolveHistoryComparisonFetchOutcome,
  resolveHistoryDetailFetchOutcome,
  resolveSetAnalysisRunImportantOutcome,
} from "../../lib/analysis-history";
import type {
  AnalysisRunDetailViewState,
  HistoryComparisonViewState,
} from "../../lib/analysis-history";

// Client component fetching this Next.js app's own Route Handler
// (app/api/analysis-runs/[id]/route.ts), same pattern as
// app/history/page.tsx fetching /api/analysis-runs. Reuses the
// existing AnalysisDashboard (the same component the top-level
// analysis result page uses) to display the saved `result` once it's
// confirmed to still match the current AnalysisResult shape — see
// docs/22_analysis_history_detail_ui_design.md.
export default function HistoryDetailPage() {
  const params = useParams<{ id: string }>();
  const id = params?.id;
  const [view, setView] = useState<AnalysisRunDetailViewState>({ kind: "loading" });
  const [comparisonView, setComparisonView] = useState<HistoryComparisonViewState>({
    kind: "loading",
  });
  // "Geminiだけ再実行" state — independent of `view` so an in-flight/
  // failed rerun never has to re-derive the whole detail view state
  // (same reasoning as app/history/page.tsx's deletingIds/deleteErrors).
  const [geminiRerunStatus, setGeminiRerunStatus] = useState<"idle" | "pending">("idle");
  const [geminiRerunError, setGeminiRerunError] = useState<string | undefined>(undefined);
  const [geminiRerunSuccessMessage, setGeminiRerunSuccessMessage] = useState<
    string | undefined
  >(undefined);
  // Important-flag toggle state — independent of `view` for the same
  // reason as geminiRerun* above. The toggle applies optimistically
  // (see handleToggleImportant below) straight onto `view.detail`.
  const [importantError, setImportantError] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function load() {
      const response = await fetch(
        `/api/analysis-runs/${encodeURIComponent(id)}`,
      ).catch(() => null);
      if (cancelled) return;

      const outcome = await resolveHistoryDetailFetchOutcome(response);
      if (cancelled) return;
      setView(outcome);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Fetched independently of the detail load above, so a comparison
  // failure never blocks the history detail body itself from
  // rendering — see docs/25_analysis_history_comparison_design.md
  // "14. エラー・データ不足時の表示方針".
  useEffect(() => {
    if (!id) return;
    let cancelled = false;

    async function load() {
      const response = await fetch(
        `/api/analysis-runs/${encodeURIComponent(id)}/comparison`,
      ).catch(() => null);
      if (cancelled) return;

      const outcome = await resolveHistoryComparisonFetchOutcome(response);
      if (cancelled) return;
      setComparisonView(outcome);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [id]);

  // Confirms, calls POST /api/analysis-runs/{id}/rerun/gemini, and on
  // success swaps `view.result` for the updated AnalysisResult the
  // backend returns — never re-fetches the whole detail, and a failed
  // rerun never touches the currently displayed result (see
  // app/lib/analysis-history.ts's resolveGeminiRerunOutcome()).
  const handleRerunGemini = async () => {
    if (!id) return;
    if (!window.confirm(GEMINI_RERUN_CONFIRM_MESSAGE)) return;

    setGeminiRerunStatus("pending");
    setGeminiRerunError(undefined);
    setGeminiRerunSuccessMessage(undefined);

    const response = await fetch(
      `/api/analysis-runs/${encodeURIComponent(id)}/rerun/gemini`,
      { method: "POST" },
    ).catch(() => null);
    const outcome = await resolveGeminiRerunOutcome(response);

    setGeminiRerunStatus("idle");

    if (!outcome.success) {
      setGeminiRerunError(outcome.message);
      return;
    }

    setGeminiRerunSuccessMessage(GEMINI_RERUN_SUCCESS_MESSAGE);
    setView((prev) => (prev.kind === "success" ? { ...prev, result: outcome.result } : prev));
  };

  // Flips `detail.isImportant` immediately (optimistic update), then
  // calls PATCH /api/analysis-runs/{id}/important — mirrors
  // app/history/page.tsx's handleToggleImportant. On failure, flips it
  // back and shows an inline error; no confirmation dialog, same
  // reasoning as the list page's toggle.
  const handleToggleImportant = async () => {
    if (!id || view.kind !== "success") return;
    const currentIsImportant = view.detail.isImportant ?? false;
    const nextIsImportant = !currentIsImportant;

    setImportantError(undefined);
    setView((prev) =>
      prev.kind === "success"
        ? { ...prev, detail: { ...prev.detail, isImportant: nextIsImportant } }
        : prev,
    );

    const response = await fetch(`/api/analysis-runs/${encodeURIComponent(id)}/important`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isImportant: nextIsImportant }),
    }).catch(() => null);
    const outcome = await resolveSetAnalysisRunImportantOutcome(response);

    if (!outcome.success) {
      setImportantError(outcome.message);
      setView((prev) =>
        prev.kind === "success"
          ? { ...prev, detail: { ...prev.detail, isImportant: currentIsImportant } }
          : prev,
      );
    }
  };

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <AppHeader />
      <div className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <Breadcrumb
            items={[{ label: "分析履歴一覧", href: "/history" }, { label: "履歴詳細" }]}
          />
          <h1 className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            {HISTORY_DETAIL_PAGE_TITLE}
          </h1>
          {/* Frames this screen as the official place to re-check a
              result now that the analysis result screen (app/page.tsx)
              is described as a preview — see
              improve/history-centered-analysis-flow. Purely a copy
              addition; this screen's actual capabilities (レポート表示・
              Geminiだけ再実行) are unchanged. */}
          <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
            {HISTORY_DETAIL_OFFICIAL_NOTE}
          </p>
        </div>
      </div>

      <main className="mx-auto max-w-5xl px-6 py-8">
        {view.kind === "loading" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_LOADING_TEXT}
          </p>
        )}

        {(view.kind === "disabled" ||
          view.kind === "forbidden" ||
          view.kind === "notFound" ||
          view.kind === "incompatible" ||
          view.kind === "error") && (
          <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            <p>{view.message}</p>
            {view.kind === "disabled" && (
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {view.detail}
              </p>
            )}
          </div>
        )}

        {view.kind === "success" && (
          <>
            <BasicInfo
              id={id}
              detail={view.detail}
              result={view.result}
              onToggleImportant={handleToggleImportant}
              importantError={importantError}
            />
            <div className="mt-6">
              <ComparisonSection view={comparisonView} />
            </div>
            <div className="mt-6">
              <AnalysisDashboard
                result={view.result}
                geminiRerun={{
                  status: geminiRerunStatus,
                  errorMessage: geminiRerunError,
                  successMessage: geminiRerunSuccessMessage,
                  onRerun: handleRerunGemini,
                }}
              />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function BasicInfo({
  id,
  detail,
  result,
  onToggleImportant,
  importantError,
}: {
  id: string | undefined;
  detail: Extract<AnalysisRunDetailViewState, { kind: "success" }>["detail"];
  result: Extract<AnalysisRunDetailViewState, { kind: "success" }>["result"];
  onToggleImportant: () => void;
  importantError: string | undefined;
}) {
  const display = formatAnalysisRunDetailBasicInfo(detail, result);
  const isImportant = detail.isImportant ?? false;

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <p className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
            {display.brandNameLabel}
          </p>
          {/* 重要フラグ切替 — タイトル周辺に置き、下のレポートリンク・
              AnalysisDashboard内のGeminiだけ再実行ボタンとは別の位置
              にする（feature/history-important-flag,
              docs/38_history_marking_design.md 案A「2. UI方針」）。 */}
          <button
            type="button"
            onClick={onToggleImportant}
            aria-pressed={isImportant}
            className="rounded-md border border-amber-300 px-2.5 py-1 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950"
          >
            <span aria-hidden="true">{isImportant ? "★" : "☆"} </span>
            {getImportantToggleLabel(isImportant)}
          </button>
          {isImportant && (
            <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
              {HISTORY_IMPORTANT_BADGE_LABEL}
            </span>
          )}
        </div>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          {display.statusLabel}
        </span>
      </div>
      {importantError && (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{importantError}</p>
      )}
      {display.canonicalDomainLabel && (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {display.canonicalDomainLabel}
        </p>
      )}
      <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-zinc-500 dark:text-zinc-400">
        <span>{display.startedAtLabel}</span>
        {display.visibilityScoreLabel && <span>{display.visibilityScoreLabel}</span>}
        {display.sourceSummaryLabel && <span>{display.sourceSummaryLabel}</span>}
      </div>
      {id && (
        <div className="mt-3">
          <Link href={buildHistoryReportPath(id)} className={REPORT_LINK_BUTTON_CLASSNAME}>
            {REPORT_LINK_TEXT}
            <span aria-hidden="true">→</span>
          </Link>
        </div>
      )}
    </div>
  );
}

/**
 * "前回比較" section — a minimal addition to the existing history
 * detail page rather than a new page (see
 * docs/25_analysis_history_comparison_design.md "7. UI設計案"「案A」).
 * Renders nothing while loading, and a small message box for every
 * non-success outcome (disabled/forbidden/notFound/noPrevious/error) —
 * a comparison failure never removes or blocks the rest of the page.
 */
function ComparisonSection({ view }: { view: HistoryComparisonViewState }) {
  if (view.kind === "loading") {
    return null;
  }

  if (view.kind !== "success") {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          {HISTORY_COMPARISON_SECTION_TITLE}
        </h2>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">{view.message}</p>
      </div>
    );
  }

  const { diff, warnings } = view.comparison;
  const visibilityScoreLabel = formatComparisonVisibilityScoreLabel(diff.visibilityScore);
  const newTerms = limitComparisonTerms(diff.cooccurrence.newTerms);
  const removedTerms = limitComparisonTerms(diff.cooccurrence.removedTerms);
  const changedTerms = limitComparisonTerms(diff.cooccurrence.changedTerms);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        {HISTORY_COMPARISON_SECTION_TITLE}
      </h2>
      <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
        {HISTORY_COMPARISON_INTRO_TEXT}
      </p>

      {warnings.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-amber-600 dark:text-amber-400">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <div className="mt-3 text-sm text-zinc-700 dark:text-zinc-300">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL}
        </p>
        <p>{visibilityScoreLabel ?? "—"}</p>
      </div>

      <div className="mt-3 text-sm text-zinc-700 dark:text-zinc-300">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {HISTORY_COMPARISON_COOCCURRENCE_LABEL}
        </p>
        <div className="mt-1 space-y-1 text-xs">
          <p>
            {HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL}:{" "}
            {newTerms.length > 0
              ? newTerms.map(formatCooccurrenceNewTermLabel).join("、")
              : "なし"}
          </p>
          <p>
            {HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL}:{" "}
            {removedTerms.length > 0
              ? removedTerms.map(formatCooccurrenceRemovedTermLabel).join("、")
              : "なし"}
          </p>
          <p>
            {HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL}:{" "}
            {changedTerms.length > 0
              ? changedTerms.map(formatCooccurrenceChangedTermLabel).join("、")
              : "なし"}
          </p>
        </div>
      </div>

      <div className="mt-3 text-sm text-zinc-700 dark:text-zinc-300">
        <p className="text-xs text-zinc-500 dark:text-zinc-400">
          {HISTORY_COMPARISON_IMPROVEMENTS_LABEL}
        </p>
        <p>{formatComparisonImprovementsLabel(diff.improvements)}</p>
      </div>
    </div>
  );
}
