"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import ReportPrintButton from "../../../components/ReportPrintButton";
import { priorityStyles, sentimentStyles, trendStyles } from "../../../lib/badge-styles";
import {
  HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL,
  HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL,
  HISTORY_COMPARISON_IMPROVEMENTS_LABEL,
  HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL,
  HISTORY_LOADING_TEXT,
  REPORT_AI_OVERVIEW_EMPTY_MESSAGE,
  REPORT_BACK_TO_DETAIL_LINK_TEXT,
  REPORT_NOTES,
  REPORT_PAGE_TITLE,
  REPORT_SECTION_TITLES,
  formatAnalysisRunDetailBasicInfo,
  formatComparisonImprovementsLabel,
  formatComparisonVisibilityScoreLabel,
  formatCooccurrenceChangedTermLabel,
  formatCooccurrenceNewTermLabel,
  formatCooccurrenceRemovedTermLabel,
  limitComparisonTerms,
  limitReportCooccurrenceTerms,
  resolveHistoryComparisonFetchOutcome,
  resolveHistoryDetailFetchOutcome,
  resolveReportComparisonMessage,
  resolveReportDetailMessage,
} from "../../../lib/analysis-history";
import type {
  AnalysisRunDetailViewState,
  HistoryComparisonViewState,
} from "../../../lib/analysis-history";
import type { AnalysisResult } from "../../../lib/types";

// Print-oriented HTML report page (docs/26_report_output_design.md).
// Fetches the same two endpoints as app/history/[id]/page.tsx (via the
// same existing frontend proxy routes — no new API, backend unchanged)
// and re-composes them into a reading-oriented layout rather than
// embedding AnalysisDashboard as-is. A comparison-fetch failure never
// blocks the rest of the report, same policy as the detail page.
export default function HistoryReportPage() {
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
    <div className="min-h-full flex-1 bg-white dark:bg-zinc-950 print:bg-white">
      <header className="border-b border-zinc-200 bg-white px-6 py-4 print:hidden dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <Link
            href={id ? `/history/${encodeURIComponent(id)}` : "/history"}
            className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
          >
            ← {REPORT_BACK_TO_DETAIL_LINK_TEXT}
          </Link>
          {view.kind === "success" && <ReportPrintButton />}
        </div>
      </header>

      <main className="mx-auto max-w-3xl px-6 py-8 print:max-w-none print:px-0 print:py-4">
        {view.kind === "loading" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">{HISTORY_LOADING_TEXT}</p>
        )}

        {view.kind !== "loading" && view.kind !== "success" && (
          <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            <p>{resolveReportDetailMessage(view)}</p>
          </div>
        )}

        {view.kind === "success" && (
          <ReportContent
            detail={view.detail}
            result={view.result}
            comparisonView={comparisonView}
          />
        )}
      </main>
    </div>
  );
}

function ReportContent({
  detail,
  result,
  comparisonView,
}: {
  detail: Extract<AnalysisRunDetailViewState, { kind: "success" }>["detail"];
  result: AnalysisResult;
  comparisonView: HistoryComparisonViewState;
}) {
  const basicInfo = formatAnalysisRunDetailBasicInfo(detail, result);
  const topTerms = limitReportCooccurrenceTerms(result.cooccurrenceRanking);

  return (
    <article className="space-y-8 text-sm text-zinc-800 dark:text-zinc-200 print:text-black">
      {/* 1. 表紙/ヘッダー */}
      <section className="border-b border-zinc-200 pb-6 dark:border-zinc-800 print:border-black">
        <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_PAGE_TITLE}
        </h1>
        <p className="mt-2 text-lg font-medium">{basicInfo.brandNameLabel}</p>
        {basicInfo.canonicalDomainLabel && (
          <p className="text-xs text-zinc-500 dark:text-zinc-400 print:text-black">
            {basicInfo.canonicalDomainLabel}
          </p>
        )}
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400 print:text-black">
          {basicInfo.startedAtLabel}
        </p>
      </section>

      {/* 2. サマリー */}
      <section>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_SECTION_TITLES.summary}
        </h2>
        {basicInfo.visibilityScoreLabel && (
          <p className="mt-2 font-medium">{basicInfo.visibilityScoreLabel}</p>
        )}
        <p className="mt-2 leading-relaxed">{result.summary.summaryText}</p>
      </section>

      {/* 3. Web上の文脈 */}
      <section>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_SECTION_TITLES.webContext}
        </h2>

        <h3 className="mt-3 text-sm font-semibold">共起語ランキング</h3>
        {topTerms.length > 0 ? (
          <ul className="mt-1 list-disc space-y-0.5 pl-5">
            {topTerms.map((term) => (
              <li key={term.keyword}>
                {term.keyword}（{term.count}件、{trendStyles[term.trend].label}）
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-zinc-500 dark:text-zinc-400 print:text-black">
            共起語ランキングデータはありません。
          </p>
        )}

        <h3 className="mt-4 text-sm font-semibold">文脈分析</h3>
        {result.contextAnalysis.length > 0 ? (
          <div className="mt-1 space-y-2">
            {result.contextAnalysis.map((item) => (
              <div key={item.context}>
                <p className="font-medium">
                  {item.context}（{sentimentStyles[item.sentiment].label}）
                </p>
                <p className="text-zinc-600 dark:text-zinc-300 print:text-black">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-1 text-zinc-500 dark:text-zinc-400 print:text-black">
            文脈分析データはありません。
          </p>
        )}
      </section>

      {/* 4. AI回答側の観測 */}
      <section>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_SECTION_TITLES.aiObservation}
        </h2>
        {result.aiOverviewComparison.length > 0 ? (
          <div className="mt-2 space-y-2">
            {result.aiOverviewComparison.map((item) => (
              <div key={item.platform}>
                <p className="font-medium">
                  {item.platform}（{item.mentioned ? "言及あり" : "言及なし"}）
                </p>
                <p className="text-zinc-600 dark:text-zinc-300 print:text-black">
                  {item.summary}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-zinc-500 dark:text-zinc-400 print:text-black">
            {REPORT_AI_OVERVIEW_EMPTY_MESSAGE}
          </p>
        )}
      </section>

      {/* 5. 前回比較 */}
      <section className="break-inside-avoid">
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_SECTION_TITLES.comparison}
        </h2>
        <ReportComparison view={comparisonView} />
      </section>

      {/* 6. 改善提案 */}
      <section>
        <h2 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50 print:text-black">
          {REPORT_SECTION_TITLES.improvements}
        </h2>
        {result.improvements.length > 0 ? (
          <div className="mt-2 space-y-2">
            {result.improvements.map((item) => (
              <div key={item.title}>
                <span
                  className={`rounded px-1.5 py-0.5 text-xs ${priorityStyles[item.priority].className}`}
                >
                  {priorityStyles[item.priority].label}
                </span>
                <p className="mt-1 font-medium">{item.title}</p>
                <p className="text-zinc-600 dark:text-zinc-300 print:text-black">
                  {item.description}
                </p>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-2 text-zinc-500 dark:text-zinc-400 print:text-black">
            改善提案データはありません。
          </p>
        )}
      </section>

      {/* 7. 注意事項 */}
      <section className="break-inside-avoid border-t border-zinc-200 pt-4 text-xs text-zinc-500 dark:border-zinc-800 dark:text-zinc-400 print:border-black print:text-black">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300 print:text-black">
          {REPORT_SECTION_TITLES.notes}
        </h2>
        <ul className="mt-1 list-disc space-y-0.5 pl-5">
          {REPORT_NOTES.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </section>
    </article>
  );
}

/**
 * Compact rendering of the "前回比較" section for the report — same
 * source data/formatting helpers as app/history/[id]/page.tsx's
 * ComparisonSection, but re-laid-out for a printed report rather than
 * a screen card. A non-success outcome never removes the rest of the
 * report (see resolveReportComparisonMessage()).
 */
function ReportComparison({ view }: { view: HistoryComparisonViewState }) {
  if (view.kind === "loading") {
    return (
      <p className="mt-2 text-zinc-500 dark:text-zinc-400 print:text-black">
        {HISTORY_LOADING_TEXT}
      </p>
    );
  }

  if (view.kind !== "success") {
    return (
      <p className="mt-2 text-zinc-500 dark:text-zinc-400 print:text-black">
        {resolveReportComparisonMessage(view)}
      </p>
    );
  }

  const { diff, warnings } = view.comparison;
  const visibilityScoreLabel = formatComparisonVisibilityScoreLabel(diff.visibilityScore);
  const newTerms = limitComparisonTerms(diff.cooccurrence.newTerms);
  const removedTerms = limitComparisonTerms(diff.cooccurrence.removedTerms);
  const changedTerms = limitComparisonTerms(diff.cooccurrence.changedTerms);

  return (
    <div className="mt-2 space-y-2">
      {warnings.length > 0 && (
        <ul className="space-y-0.5 text-xs text-amber-600 dark:text-amber-400 print:text-black">
          {warnings.map((warning) => (
            <li key={warning}>{warning}</li>
          ))}
        </ul>
      )}

      <p>
        <span className="text-xs text-zinc-500 dark:text-zinc-400 print:text-black">
          {HISTORY_COMPARISON_VISIBILITY_SCORE_LABEL}:{" "}
        </span>
        {visibilityScoreLabel ?? "—"}
      </p>

      <div>
        <p className="text-xs text-zinc-500 dark:text-zinc-400 print:text-black">
          {HISTORY_COMPARISON_COOCCURRENCE_LABEL}
        </p>
        <p className="text-xs">
          {HISTORY_COMPARISON_COOCCURRENCE_NEW_LABEL}:{" "}
          {newTerms.length > 0
            ? newTerms.map(formatCooccurrenceNewTermLabel).join("、")
            : "なし"}
        </p>
        <p className="text-xs">
          {HISTORY_COMPARISON_COOCCURRENCE_REMOVED_LABEL}:{" "}
          {removedTerms.length > 0
            ? removedTerms.map(formatCooccurrenceRemovedTermLabel).join("、")
            : "なし"}
        </p>
        <p className="text-xs">
          {HISTORY_COMPARISON_COOCCURRENCE_CHANGED_LABEL}:{" "}
          {changedTerms.length > 0
            ? changedTerms.map(formatCooccurrenceChangedTermLabel).join("、")
            : "なし"}
        </p>
      </div>

      <p>
        <span className="text-xs text-zinc-500 dark:text-zinc-400 print:text-black">
          {HISTORY_COMPARISON_IMPROVEMENTS_LABEL}:{" "}
        </span>
        {formatComparisonImprovementsLabel(diff.improvements)}
      </p>
    </div>
  );
}
