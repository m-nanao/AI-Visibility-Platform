"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AppHeader from "../components/AppHeader";
import { DETAIL_LINK_BUTTON_CLASSNAME } from "../lib/link-button-styles";
import {
  HISTORY_DELETE_BUTTON_LABEL,
  HISTORY_DELETE_CONFIRM_MESSAGE,
  HISTORY_PAGE_TITLE,
  HISTORY_PAGE_DESCRIPTION,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_LOADING_TEXT,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  buildHistoryDetailPath,
  formatAnalysisRunListItem,
  resolveDeleteAnalysisRunOutcome,
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
  // Tracks per-row delete-in-progress/error state, keyed by analysis
  // run id — independent of `view` so an in-flight/failed delete never
  // has to re-derive the whole list view state.
  const [deletingIds, setDeletingIds] = useState<Set<string>>(new Set());
  const [deleteErrors, setDeleteErrors] = useState<Record<string, string>>({});

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

  // Confirms, calls DELETE /api/analysis-runs/{id}, and on success
  // removes the row from the current list view immediately (switching
  // to the empty view when it was the last one) rather than
  // re-fetching the whole list. A failed delete never removes the row
  // — the error is shown inline on that same row instead.
  const handleDelete = async (id: string) => {
    if (!window.confirm(HISTORY_DELETE_CONFIRM_MESSAGE)) return;

    setDeletingIds((prev) => new Set(prev).add(id));
    setDeleteErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });

    const response = await fetch(`/api/analysis-runs/${encodeURIComponent(id)}`, {
      method: "DELETE",
    }).catch(() => null);
    const outcome = await resolveDeleteAnalysisRunOutcome(response);

    setDeletingIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

    if (!outcome.success) {
      setDeleteErrors((prev) => ({ ...prev, [id]: outcome.message }));
      return;
    }

    setView((prev) => {
      if (prev.kind !== "items") return prev;
      const remaining = prev.items.filter((item) => item.id !== id);
      return remaining.length === 0 ? { kind: "empty" } : { kind: "items", items: remaining };
    });
  };

  return (
    <div className="min-h-full flex-1 bg-zinc-50 dark:bg-zinc-950">
      <AppHeader />
      <div className="border-b border-zinc-200 bg-white dark:border-zinc-800 dark:bg-zinc-900">
        <div className="mx-auto max-w-5xl px-6 py-4">
          <h1 className="text-lg font-semibold text-zinc-900 dark:text-zinc-50">
            {HISTORY_PAGE_TITLE}
          </h1>
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_PAGE_DESCRIPTION}
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

        {view.kind === "empty" && (
          <p className="text-sm text-zinc-500 dark:text-zinc-400">
            {HISTORY_EMPTY_STATE_TEXT}
          </p>
        )}

        {view.kind === "items" && (
          <ul className="space-y-3">
            {view.items.map((item) => {
              const display = formatAnalysisRunListItem(item);
              const isDeleting = deletingIds.has(item.id);
              const deleteError = deleteErrors[item.id];
              return (
                <li
                  key={item.id}
                  className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <div className="flex items-center justify-between gap-2">
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
                  {/* 観測モードバッジ — どのAI Overview/ChatGPT/Claude/
                      Gemini/Common Crawlが有効だったかを一覧で見分ける
                      ため（feature/history-delete-and-mode-badges）。古
                      い履歴はformatModeSummaryBadges()がすべて「不明」
                      にフォールバックするため表示は壊れない。 */}
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {display.modeBadges.map((badge) => (
                      <span
                        key={badge.label}
                        className="rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
                      >
                        {badge.label}: {badge.value}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <Link
                      href={buildHistoryDetailPath(item.id)}
                      className={DETAIL_LINK_BUTTON_CLASSNAME}
                    >
                      {HISTORY_LIST_DETAIL_LINK_TEXT}
                      <span aria-hidden="true">→</span>
                    </Link>
                    <button
                      type="button"
                      onClick={() => handleDelete(item.id)}
                      disabled={isDeleting}
                      className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                    >
                      {isDeleting ? "削除中..." : HISTORY_DELETE_BUTTON_LABEL}
                    </button>
                  </div>
                  {deleteError && (
                    <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                      {deleteError}
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </main>
    </div>
  );
}
