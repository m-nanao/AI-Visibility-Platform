"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  HISTORY_PAGE_TITLE,
  HISTORY_PAGE_DESCRIPTION,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_LOADING_TEXT,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  buildHistoryDetailPath,
  formatAnalysisRunListItem,
  resolveHistoryFetchOutcome,
} from "../lib/analysis-history";
import type { HistoryViewState } from "../lib/analysis-history";

// Client component fetching this Next.js app's own Route Handler
// (app/api/analysis-runs/route.ts), same pattern as app/page.tsx
// fetching /api/analyze. Detail pages (/history/[id]) are implemented
// in app/history/[id]/page.tsx — see
// docs/22_analysis_history_detail_ui_design.md.
export default function HistoryPage() {
  const [view, setView] = useState<HistoryViewState>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;

    async function load() {
      const response = await fetch("/api/analysis-runs?limit=20&offset=0").catch(
        () => null,
      );
      if (cancelled) return;

      const outcome = await resolveHistoryFetchOutcome(response);
      if (cancelled) return;
      setView(outcome);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <header className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <Link
            href="/"
            className="text-sm text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
          >
            ← 分析に戻る
          </Link>
          <h1 className="mt-2 text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            {HISTORY_PAGE_TITLE}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_PAGE_DESCRIPTION}
          </p>
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-6 py-8">
        {view.kind === "loading" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_LOADING_TEXT}
          </p>
        )}

        {(view.kind === "disabled" || view.kind === "error") && (
          <div className="rounded-lg border border-zinc-200 bg-white p-5 text-sm text-zinc-700 shadow-sm dark:border-zinc-800 dark:bg-zinc-900 dark:text-zinc-300">
            <p>{view.message}</p>
            {view.kind === "disabled" && (
              <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
                {view.detail}
              </p>
            )}
          </div>
        )}

        {view.kind === "empty" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_EMPTY_STATE_TEXT}
          </p>
        )}

        {view.kind === "items" && (
          <ul className="space-y-3">
            {view.items.map((item) => {
              const display = formatAnalysisRunListItem(item);
              return (
                <li
                  key={item.id}
                  className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
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
                    {display.visibilityScoreLabel && (
                      <span>{display.visibilityScoreLabel}</span>
                    )}
                    {display.sourceSummaryLabel && (
                      <span>{display.sourceSummaryLabel}</span>
                    )}
                  </div>
                  <Link
                    href={buildHistoryDetailPath(item.id)}
                    className="mt-2 inline-block text-xs text-zinc-500 underline-offset-2 hover:underline dark:text-zinc-400"
                  >
                    {HISTORY_LIST_DETAIL_LINK_TEXT}
                  </Link>
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </div>
  );
}
