"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import AnalysisDashboard from "../../components/AnalysisDashboard";
import {
  HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL,
  HISTORY_COMPARISON_IMPROVEMENTS_LABEL,
  HISTORY_COMPARISON_SECTION_TITLE,
  HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL,
  HISTORY_DETAIL_BACK_LINK_TEXT,
  HISTORY_DETAIL_PAGE_TITLE,
  HISTORY_LOADING_TEXT,
  formatAnalysisRunDetailBasicInfo,
  formatComparisonImprovementsLabel,
  formatComparisonVisibilityScoreLabel,
  formatCooccurrenceChangedTermLabel,
  formatCooccurrenceNewTermLabel,
  formatCooccurrenceRemovedTermLabel,
  limitComparisonTerms,
  resolveHistoryComparisonFetchOutcome,
  resolveHistoryDetailFetchOutcome,
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

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <Link
            href="/history"
            className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
          >
            ← {HISTORY_DETAIL_BACK_LINK_TEXT}
          </Link>
          <h1 className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            {HISTORY_DETAIL_PAGE_TITLE}
          </h1>
        </div>
      </header>

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
            <BasicInfo detail={view.detail} result={view.result} />
            <div className="mt-6">
              <ComparisonSection view={comparisonView} />
            </div>
            <div className="mt-6">
              <AnalysisDashboard result={view.result} />
            </div>
          </>
        )}
      </main>
    </div>
  );
}

function BasicInfo({
  detail,
  result,
}: {
  detail: Extract<AnalysisRunDetailViewState, { kind: "success" }>["detail"];
  result: Extract<AnalysisRunDetailViewState, { kind: "success" }>["result"];
}) {
  const display = formatAnalysisRunDetailBasicInfo(detail, result);

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex items-center justify-between">
        <p className="text-base font-semibold text-zinc-900 dark:text-zinc-50">
          {display.brandNameLabel}
        </p>
        <span className="rounded bg-zinc-100 px-1.5 py-0.5 text-xs text-zinc-500 dark:bg-zinc-800 dark:text-zinc-400">
          {display.statusLabel}
        </span>
      </div>
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
