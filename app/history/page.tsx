"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppHeader from "../components/AppHeader";
import { DETAIL_LINK_BUTTON_CLASSNAME } from "../lib/link-button-styles";
import {
  HISTORY_DELETE_BUTTON_LABEL,
  HISTORY_DELETE_CONFIRM_MESSAGE,
  HISTORY_IMPORTANT_BADGE_LABEL,
  HISTORY_PAGE_TITLE,
  HISTORY_PAGE_DESCRIPTION,
  HISTORY_EMPTY_STATE_TEXT,
  HISTORY_LOADING_TEXT,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  HISTORY_SEARCH_NO_RESULTS_TEXT,
  HISTORY_SEARCH_PLACEHOLDER,
  HISTORY_SORT_DEFAULT_ORDER,
  HISTORY_SORT_NEWEST_LABEL,
  HISTORY_SORT_OLDEST_LABEL,
  buildHistoryDetailPath,
  filterAnalysisRunListItems,
  formatAnalysisRunListItem,
  formatHistoryCountLabel,
  getImportantToggleLabel,
  resolveDeleteAnalysisRunOutcome,
  resolveHistoryFetchOutcome,
  resolveSetAnalysisRunImportantOutcome,
  sortAnalysisRunListItems,
} from "../lib/analysis-history";
import type { HistorySortOrder, HistoryViewState } from "../lib/analysis-history";

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
  // Tracks per-row important-flag update errors, keyed by analysis run
  // id — independent of `view` since the toggle itself applies
  // optimistically straight to `view.items` (see handleToggleImportant
  // below) rather than waiting for the PATCH to resolve.
  const [importantErrors, setImportantErrors] = useState<Record<string, string>>({});
  // Search/sort are purely client-side over the already-fetched page of
  // items (no new backend search API, no re-fetch) — see
  // app/lib/analysis-history.ts's filterAnalysisRunListItems()/
  // sortAnalysisRunListItems().
  const [searchQuery, setSearchQuery] = useState("");
  const [sortOrder, setSortOrder] = useState<HistorySortOrder>(HISTORY_SORT_DEFAULT_ORDER);

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

  // Flips `isImportant` on the matching row immediately (optimistic
  // update), then calls PATCH /api/analysis-runs/{id}/important. On
  // failure, flips it back to the pre-click value and shows an inline
  // error on that row — the row's displayed state and the backend's
  // state never silently disagree past that point. No confirmation
  // dialog (unlike handleDelete above): toggling is reversible with
  // another click, so a confirm would only add friction.
  const handleToggleImportant = async (id: string, currentIsImportant: boolean) => {
    const nextIsImportant = !currentIsImportant;

    setImportantErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setView((prev) => {
      if (prev.kind !== "items") return prev;
      return {
        kind: "items",
        items: prev.items.map((item) =>
          item.id === id ? { ...item, isImportant: nextIsImportant } : item,
        ),
      };
    });

    const response = await fetch(`/api/analysis-runs/${encodeURIComponent(id)}/important`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isImportant: nextIsImportant }),
    }).catch(() => null);
    const outcome = await resolveSetAnalysisRunImportantOutcome(response);

    if (!outcome.success) {
      setImportantErrors((prev) => ({ ...prev, [id]: outcome.message }));
      setView((prev) => {
        if (prev.kind !== "items") return prev;
        return {
          kind: "items",
          items: prev.items.map((item) =>
            item.id === id ? { ...item, isImportant: currentIsImportant } : item,
          ),
        };
      });
    }
  };

  // Recomputed from `view.items` on every render — cheap at this list's
  // scale (a single fetched page, see the limit=20 query below) and
  // keeps search/sort entirely derived state rather than something
  // that could drift from `view` after a delete.
  const allItems = useMemo(() => (view.kind === "items" ? view.items : []), [view]);
  const visibleItems = useMemo(
    () => sortAnalysisRunListItems(filterAnalysisRunListItems(allItems, searchQuery), sortOrder),
    [allItems, searchQuery, sortOrder],
  );
  const countLabel = formatHistoryCountLabel(allItems.length, visibleItems.length);

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
          <>
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="sm:max-w-xs sm:flex-1">
                <label htmlFor="historySearch" className="sr-only">
                  {HISTORY_SEARCH_PLACEHOLDER}
                </label>
                <input
                  id="historySearch"
                  type="text"
                  value={searchQuery}
                  onChange={(event) => setSearchQuery(event.target.value)}
                  placeholder={HISTORY_SEARCH_PLACEHOLDER}
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="historySortOrder" className="text-xs text-zinc-500 dark:text-zinc-400">
                  並び替え
                </label>
                <select
                  id="historySortOrder"
                  value={sortOrder}
                  onChange={(event) => setSortOrder(event.target.value as HistorySortOrder)}
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  <option value="newest">{HISTORY_SORT_NEWEST_LABEL}</option>
                  <option value="oldest">{HISTORY_SORT_OLDEST_LABEL}</option>
                </select>
              </div>
            </div>
            <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{countLabel}</p>

            {visibleItems.length === 0 && (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                {HISTORY_SEARCH_NO_RESULTS_TEXT}
              </p>
            )}

            <ul className="space-y-3">
            {visibleItems.map((item) => {
              const display = formatAnalysisRunListItem(item);
              const isDeleting = deletingIds.has(item.id);
              const deleteError = deleteErrors[item.id];
              const isImportant = item.isImportant ?? false;
              const importantError = importantErrors[item.id];
              return (
                <li
                  key={item.id}
                  className="rounded-lg border border-zinc-200 bg-white p-4 shadow-sm dark:border-zinc-800 dark:bg-zinc-900"
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <p className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
                        {display.brandNameLabel}
                      </p>
                      {/* 重要フラグbadge — isImportant===trueの場合のみ表示
                          (feature/history-important-flag,
                          docs/38_history_marking_design.md 案A)。切替
                          ボタンは削除/詳細リンクと混同しない下部の行に
                          置く。 */}
                      {isImportant && (
                        <span className="rounded bg-amber-100 px-1.5 py-0.5 text-xs font-medium text-amber-700 dark:bg-amber-900/40 dark:text-amber-300">
                          ★ {HISTORY_IMPORTANT_BADGE_LABEL}
                        </span>
                      )}
                    </div>
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
                  <div className="mt-2 flex min-w-0 flex-wrap gap-1.5">
                    {display.modeBadges.map((badge) => (
                      <span
                        key={badge.label}
                        className="max-w-full rounded bg-zinc-100 px-1.5 py-0.5 text-[10px] break-words text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
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
                      onClick={() => handleToggleImportant(item.id, isImportant)}
                      aria-pressed={isImportant}
                      className="rounded-md border border-amber-300 px-3 py-1.5 text-xs font-medium text-amber-700 transition-colors hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-950"
                    >
                      <span aria-hidden="true">{isImportant ? "★" : "☆"} </span>
                      {getImportantToggleLabel(isImportant)}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDelete(item.id)}
                      disabled={isDeleting}
                      className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                    >
                      {isDeleting ? "削除中..." : HISTORY_DELETE_BUTTON_LABEL}
                    </button>
                  </div>
                  {importantError && (
                    <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                      {importantError}
                    </p>
                  )}
                  {deleteError && (
                    <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                      {deleteError}
                    </p>
                  )}
                </li>
              );
            })}
            </ul>
          </>
        )}
      </main>
    </div>
  );
}
