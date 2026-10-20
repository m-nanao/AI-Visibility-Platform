"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import AppHeader from "../components/AppHeader";
import { DETAIL_LINK_BUTTON_CLASSNAME } from "../lib/link-button-styles";
import {
  AI_OVERVIEW_OBSERVATION_FILTER_LABELS,
  AI_OVERVIEW_OBSERVATION_FILTER_LABEL_TEXT,
  CHATGPT_OBSERVATION_FILTER_LABEL_TEXT,
  CLAUDE_OBSERVATION_FILTER_LABEL_TEXT,
  GEMINI_OBSERVATION_FILTER_LABEL_TEXT,
  HISTORY_CATEGORY_FILTER_ALL_VALUE,
  HISTORY_CATEGORY_FILTER_LABEL_TEXT,
  HISTORY_CATEGORY_FILTER_UNCATEGORIZED_VALUE,
  HISTORY_CLEAR_FILTERS_BUTTON_LABEL,
  HISTORY_CLEAR_FILTERS_RESETS_SORT,
  HISTORY_DELETE_BUTTON_LABEL,
  HISTORY_DELETE_CONFIRM_MESSAGE,
  HISTORY_FAVORITE_BADGE_LABEL,
  HISTORY_FAVORITE_FILTER_ALL_LABEL,
  HISTORY_FAVORITE_FILTER_DEFAULT,
  HISTORY_FAVORITE_FILTER_FAVORITE_ONLY_LABEL,
  HISTORY_FILTERS_PANEL_HIDE_LABEL,
  HISTORY_FILTERS_PANEL_SHOW_LABEL,
  HISTORY_IMPORTANT_BADGE_LABEL,
  HISTORY_IMPORTANT_FILTER_ALL_LABEL,
  HISTORY_IMPORTANT_FILTER_DEFAULT,
  HISTORY_IMPORTANT_FILTER_IMPORTANT_ONLY_LABEL,
  HISTORY_PAGE_TITLE,
  HISTORY_PAGE_DESCRIPTION,
  HISTORY_LOADING_TEXT,
  HISTORY_LIST_DETAIL_LINK_TEXT,
  HISTORY_SEARCH_PLACEHOLDER,
  HISTORY_SORT_DEFAULT_ORDER,
  HISTORY_SORT_NEWEST_LABEL,
  HISTORY_SORT_OLDEST_LABEL,
  HISTORY_LIST_PAGE_SIZE,
  HISTORY_TAG_FILTER_LABEL_TEXT,
  OBSERVATION_FILTER_DEFAULT,
  SIMPLE_PROVIDER_OBSERVATION_FILTER_LABELS,
  buildHistoryListRequestUrl,
  canManageHistoryListItem,
  describeActiveHistoryFilters,
  formatAnalysisRunListItem,
  formatHistoryPaginationLabel,
  getFavoriteToggleLabel,
  getImportantToggleLabel,
  isHistoryListQueryFiltered,
  resolveDeleteAnalysisRunOutcome,
  resolveHistoryFetchOutcome,
  resolveHistoryListItemDetailPath,
  resolveServerFilteredEmptyText,
  resolveSetAnalysisRunFavoriteOutcome,
  resolveSetAnalysisRunImportantOutcome,
} from "../lib/analysis-history";
import type {
  HistoryCategoryFilterValue,
  HistoryFavoriteFilter,
  HistoryImportantFilter,
  HistoryListQuery,
  HistorySortOrder,
  HistoryViewState,
  ObservationFilterValue,
} from "../lib/analysis-history";
import {
  UNCATEGORIZED_LABEL,
  resolveCategoryListFetchOutcome,
  resolveTagListFetchOutcome,
} from "../lib/tags-categories";
import type { CategoryItem, TagItem } from "../lib/tags-categories";

// Select-box value type for the 4 AI observation filters — "all" (no
// filter) plus the 5 ObservationFilterValue states, matching this
// task's "4. UI"'s "すべて" + 5-state list.
type ObservationFilterSelectValue = "all" | ObservationFilterValue;

// Debounce delay for the search input — long enough to avoid firing a
// request per keystroke, short enough to still feel responsive. The
// debounced value (not the raw input) is what the fetch effect below
// depends on.
const SEARCH_DEBOUNCE_MS = 300;

// Client component fetching this Next.js app's own Route Handler
// (app/api/analysis-runs/route.ts), same pattern as app/page.tsx
// fetching /api/analyze. Search/important-filter/date-range/sort/
// pagination are all server-side (feature/history-server-side-search-
// pagination) — this page only builds the query string and renders
// the response, it never filters/sorts the items itself. Detail pages
// (/history/[id]) are implemented in app/history/[id]/page.tsx — see
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
  // Tracks per-row favorite-toggle-in-progress/error state, keyed by
  // analysis run id (feature/history-favorite-flag) — unlike
  // handleToggleImportant above, this one *is* double-click-guarded
  // (favoriteTogglingIds also disables the button while a request is
  // in flight), per this task's explicit "二重クリック対策"
  // requirement.
  const [favoriteTogglingIds, setFavoriteTogglingIds] = useState<Set<string>>(new Set());
  const [favoriteErrors, setFavoriteErrors] = useState<Record<string, string>>({});

  const [page, setPage] = useState(1);
  // `searchInput` is the raw, every-keystroke value shown in the text
  // box; `debouncedSearch` is what actually goes into the server
  // query (see the debounce effect below) — keeping them separate is
  // what lets the input feel instant while still only firing one
  // fetch per pause in typing.
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");
  const [importantFilter, setImportantFilter] = useState<HistoryImportantFilter>(
    HISTORY_IMPORTANT_FILTER_DEFAULT,
  );
  const [sortOrder, setSortOrder] = useState<HistorySortOrder>(HISTORY_SORT_DEFAULT_ORDER);
  // Plain "YYYY-MM-DD" from <input type="date">, or "" when unset —
  // see buildHistoryListRequestUrl()'s JST conversion.
  const [startedFrom, setStartedFrom] = useState("");
  const [startedTo, setStartedTo] = useState("");
  // AI観測状態フィルター (feature/history-ai-observation-filter) — 4
  // independent selects, each defaulting to "すべて" (no filter).
  const [aiOverviewObservation, setAiOverviewObservation] =
    useState<ObservationFilterSelectValue>(OBSERVATION_FILTER_DEFAULT);
  const [chatgptObservation, setChatgptObservation] =
    useState<ObservationFilterSelectValue>(OBSERVATION_FILTER_DEFAULT);
  const [claudeObservation, setClaudeObservation] =
    useState<ObservationFilterSelectValue>(OBSERVATION_FILTER_DEFAULT);
  const [geminiObservation, setGeminiObservation] =
    useState<ObservationFilterSelectValue>(OBSERVATION_FILTER_DEFAULT);
  // 「お気に入りのみ表示」フィルタ (feature/history-favorite-flag) —
  // すべて/お気に入りのみの2択トグル、重要フラグとは完全に独立した状態。
  const [favoriteFilter, setFavoriteFilter] = useState<HistoryFavoriteFilter>(
    HISTORY_FAVORITE_FILTER_DEFAULT,
  );
  // カテゴリ/タグフィルタ (feature/history-tags-categories, Task 5-C) —
  // 既存フィルタと同じ「選択したら page を1に戻す」規約。
  // categoryFilter は "all"/"uncategorized"/実際のカテゴリid のいずれか
  // (HistoryCategoryFilterValue)。selectedTagIds は複数選択可・OR条件。
  const [categoryFilter, setCategoryFilter] = useState<HistoryCategoryFilterValue>(
    HISTORY_CATEGORY_FILTER_ALL_VALUE,
  );
  const [selectedTagIds, setSelectedTagIds] = useState<string[]>([]);
  // フィルタパネルの開閉状態 — 既存フィルタ・新規フィルタをまとめて
  // collapsible panel に入れる（Task 5-C「4. UI」）。デフォルトは閉じた
  // 状態で、フィルタが実際に効いていれば自動的に開く（下のuseEffect）。
  const [filtersPanelOpen, setFiltersPanelOpen] = useState(false);
  // タグ/カテゴリの選択肢一覧 — フィルタのセレクト/複数選択用。一覧
  // ページそのものの読み込み失敗とは独立させ、taking最小限の非ブロッキ
  // ング表示にする（一覧の表示自体は壊さない）。
  const [availableTags, setAvailableTags] = useState<TagItem[]>([]);
  const [availableCategories, setAvailableCategories] = useState<CategoryItem[]>([]);

  // Debounces `searchInput` into `debouncedSearch`, and resets to page
  // 1 in the same tick so a search doesn't fetch twice (once for the
  // new search, once for the page reset) — this task's "フィルタ変更
  //時はページ1にリセットする".
  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearch(searchInput);
      setPage(1);
    }, SEARCH_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [searchInput]);

  const handleImportantFilterChange = (next: HistoryImportantFilter) => {
    setImportantFilter(next);
    setPage(1);
  };
  const handleSortOrderChange = (next: HistorySortOrder) => {
    setSortOrder(next);
    setPage(1);
  };
  const handleStartedFromChange = (value: string) => {
    setStartedFrom(value);
    setPage(1);
  };
  const handleStartedToChange = (value: string) => {
    setStartedTo(value);
    setPage(1);
  };
  const handleAiOverviewObservationChange = (value: ObservationFilterSelectValue) => {
    setAiOverviewObservation(value);
    setPage(1);
  };
  const handleChatgptObservationChange = (value: ObservationFilterSelectValue) => {
    setChatgptObservation(value);
    setPage(1);
  };
  const handleClaudeObservationChange = (value: ObservationFilterSelectValue) => {
    setClaudeObservation(value);
    setPage(1);
  };
  const handleGeminiObservationChange = (value: ObservationFilterSelectValue) => {
    setGeminiObservation(value);
    setPage(1);
  };
  const handleFavoriteFilterChange = (next: HistoryFavoriteFilter) => {
    setFavoriteFilter(next);
    setPage(1);
  };
  const handleCategoryFilterChange = (next: HistoryCategoryFilterValue) => {
    setCategoryFilter(next);
    setPage(1);
  };
  const handleTagFilterToggle = (tagId: string) => {
    setSelectedTagIds((prev) =>
      prev.includes(tagId) ? prev.filter((id) => id !== tagId) : [...prev, tagId],
    );
    setPage(1);
  };
  // 「条件をクリア」— すべてのフィルタを初期値に戻す。並び替えも対象に
  // 含める（HISTORY_CLEAR_FILTERS_RESETS_SORTのコメント参照）。検索欄
  // は searchInput/debouncedSearch の両方をクリアする必要がある —
  // debouncedSearchだけ戻すとsearchInputが古い値を表示したまま残る。
  const handleClearFilters = () => {
    setSearchInput("");
    setDebouncedSearch("");
    setImportantFilter(HISTORY_IMPORTANT_FILTER_DEFAULT);
    setFavoriteFilter(HISTORY_FAVORITE_FILTER_DEFAULT);
    setStartedFrom("");
    setStartedTo("");
    setAiOverviewObservation(OBSERVATION_FILTER_DEFAULT);
    setChatgptObservation(OBSERVATION_FILTER_DEFAULT);
    setClaudeObservation(OBSERVATION_FILTER_DEFAULT);
    setGeminiObservation(OBSERVATION_FILTER_DEFAULT);
    setCategoryFilter(HISTORY_CATEGORY_FILTER_ALL_VALUE);
    setSelectedTagIds([]);
    if (HISTORY_CLEAR_FILTERS_RESETS_SORT) {
      setSortOrder(HISTORY_SORT_DEFAULT_ORDER);
    }
    setPage(1);
  };

  const query: HistoryListQuery = useMemo(
    () => ({
      search: debouncedSearch,
      important: importantFilter === "importantOnly",
      startedFrom: startedFrom || undefined,
      startedTo: startedTo || undefined,
      aiOverviewObservation:
        aiOverviewObservation === "all" ? undefined : aiOverviewObservation,
      chatgptObservation: chatgptObservation === "all" ? undefined : chatgptObservation,
      claudeObservation: claudeObservation === "all" ? undefined : claudeObservation,
      geminiObservation: geminiObservation === "all" ? undefined : geminiObservation,
      favorite: favoriteFilter === "favoriteOnly",
      uncategorizedOnly: categoryFilter === HISTORY_CATEGORY_FILTER_UNCATEGORIZED_VALUE,
      categoryId:
        categoryFilter !== HISTORY_CATEGORY_FILTER_ALL_VALUE &&
        categoryFilter !== HISTORY_CATEGORY_FILTER_UNCATEGORIZED_VALUE
          ? categoryFilter
          : undefined,
      tagIds: selectedTagIds.length > 0 ? selectedTagIds : undefined,
      sort: sortOrder,
      page,
    }),
    [
      debouncedSearch,
      importantFilter,
      startedFrom,
      startedTo,
      aiOverviewObservation,
      chatgptObservation,
      claudeObservation,
      geminiObservation,
      favoriteFilter,
      categoryFilter,
      selectedTagIds,
      sortOrder,
      page,
    ],
  );

  useEffect(() => {
    let cancelled = false;

    async function load() {
      setView({ kind: "loading" });
      const response = await fetch(buildHistoryListRequestUrl(query)).catch(() => null);
      if (cancelled) return;

      const outcome = await resolveHistoryFetchOutcome(response);
      if (cancelled) return;
      setView(outcome);
    }

    load();
    return () => {
      cancelled = true;
    };
  }, [query]);

  // タグ/カテゴリの選択肢一覧を一度だけ取得 — 失敗してもフィルタUIが
  // 「選択肢なし」で表示されるだけで、履歴一覧本体の表示は妨げない
  // （Task 5-C「3. 操作性」のnever-show-false-success方針と同じく、
  // ここでも読み込み失敗を握りつぶさず、単に選択肢を空のままにする）。
  useEffect(() => {
    let cancelled = false;

    async function loadOptions() {
      const [tagsResponse, categoriesResponse] = await Promise.all([
        fetch("/api/tags").catch(() => null),
        fetch("/api/categories").catch(() => null),
      ]);
      if (cancelled) return;

      const tagsOutcome = await resolveTagListFetchOutcome(tagsResponse);
      const categoriesOutcome = await resolveCategoryListFetchOutcome(categoriesResponse);
      if (cancelled) return;

      if (tagsOutcome.success) setAvailableTags(tagsOutcome.tags);
      if (categoriesOutcome.success) setAvailableCategories(categoriesOutcome.categories);
    }

    loadOptions();
    return () => {
      cancelled = true;
    };
  }, []);

  // Confirms, calls DELETE /api/analysis-runs/{id}, and on success
  // removes the row from the current list view immediately (adjusting
  // `total` down by one) rather than re-fetching the whole list. A
  // failed delete never removes the row — the error is shown inline
  // on that same row instead.
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
      return {
        kind: "items",
        items: prev.items.filter((item) => item.id !== id),
        total: Math.max(0, prev.total - 1),
        limit: prev.limit,
        offset: prev.offset,
      };
    });
  };

  // Flips `isImportant` on the matching row immediately (optimistic
  // update), then calls PATCH /api/analysis-runs/{id}/important. On
  // failure, flips it back to the pre-click value and shows an inline
  // error on that row — the row's displayed state and the backend's
  // state never silently disagree past that point. No confirmation
  // dialog (unlike handleDelete above): toggling is reversible with
  // another click, so a confirm would only add friction.
  //
  // Note: while "重要のみ" is active, toggling a row off no longer
  // live-removes it from view (filtering now happens server-side, on
  // the next fetch) — it stays visible, now unchecked, until the next
  // page load. Acceptable trade-off for this task's scope.
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
        ...prev,
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
          ...prev,
          items: prev.items.map((item) =>
            item.id === id ? { ...item, isImportant: currentIsImportant } : item,
          ),
        };
      });
    }
  };

  // Flips `isFavorite` on the matching row (optimistic update), then
  // calls PATCH /api/analysis-runs/{id}/favorite — mirrors
  // handleToggleImportant above, with one deliberate addition: this
  // task's "二重クリック対策" requires guarding against a second click
  // while the first request is still in flight, so `favoriteTogglingIds`
  // both disables the button (see the JSX below) and short-circuits
  // here as a second line of defense. On failure, rolls back to the
  // pre-click value and shows an inline error on that row, same as
  // handleToggleImportant. Entirely independent of isImportant — never
  // reads or writes it.
  const handleToggleFavorite = async (id: string, currentIsFavorite: boolean) => {
    if (favoriteTogglingIds.has(id)) return;

    const nextIsFavorite = !currentIsFavorite;

    setFavoriteTogglingIds((prev) => new Set(prev).add(id));
    setFavoriteErrors((prev) => {
      const next = { ...prev };
      delete next[id];
      return next;
    });
    setView((prev) => {
      if (prev.kind !== "items") return prev;
      return {
        ...prev,
        items: prev.items.map((item) =>
          item.id === id ? { ...item, isFavorite: nextIsFavorite } : item,
        ),
      };
    });

    const response = await fetch(`/api/analysis-runs/${encodeURIComponent(id)}/favorite`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ isFavorite: nextIsFavorite }),
    }).catch(() => null);
    const outcome = await resolveSetAnalysisRunFavoriteOutcome(response);

    setFavoriteTogglingIds((prev) => {
      const next = new Set(prev);
      next.delete(id);
      return next;
    });

    if (!outcome.success) {
      setFavoriteErrors((prev) => ({ ...prev, [id]: outcome.message }));
      setView((prev) => {
        if (prev.kind !== "items") return prev;
        return {
          ...prev,
          items: prev.items.map((item) =>
            item.id === id ? { ...item, isFavorite: currentIsFavorite } : item,
          ),
        };
      });
    }
  };

  const items = view.kind === "items" ? view.items : [];
  const total = view.kind === "items" ? view.total : 0;
  const totalPages = Math.max(1, Math.ceil(total / HISTORY_LIST_PAGE_SIZE));
  const paginationLabel = formatHistoryPaginationLabel(total, page);
  const emptyResultsText = resolveServerFilteredEmptyText(isHistoryListQueryFiltered(query));
  const selectedCategoryName = availableCategories.find((c) => c.id === categoryFilter)?.name;
  const selectedTagNames = availableTags
    .filter((tag) => selectedTagIds.includes(tag.id))
    .map((tag) => tag.name);
  const activeFilterLines = describeActiveHistoryFilters(query, {
    categoryName: selectedCategoryName,
    tagNames: selectedTagNames,
  });

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
        {view.kind === "loading" && items.length === 0 && (
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

        {(view.kind === "items" || (view.kind === "loading" && items.length > 0)) && (
          <>
            {/* フィルタパネルの開閉トグル + 現在の条件サマリー
                （Task 5-C「4. UI」— 検索・重要/お気に入り・日付範囲・4つ
                のAI観測状態 + 新規のカテゴリ/タグを1つの collapsible
                panelにまとめ、現在有効な条件を一覧できるようにする）。 */}
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <button
                type="button"
                onClick={() => setFiltersPanelOpen((prev) => !prev)}
                aria-expanded={filtersPanelOpen}
                className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
              >
                {filtersPanelOpen ? HISTORY_FILTERS_PANEL_HIDE_LABEL : HISTORY_FILTERS_PANEL_SHOW_LABEL}
              </button>
              {activeFilterLines.length > 0 && (
                <button
                  type="button"
                  onClick={handleClearFilters}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  {HISTORY_CLEAR_FILTERS_BUTTON_LABEL}
                </button>
              )}
            </div>
            {activeFilterLines.length > 0 && (
              <div className="mb-4 flex flex-wrap gap-1.5">
                {activeFilterLines.map((line) => (
                  <span
                    key={line}
                    className="rounded bg-zinc-100 px-2 py-1 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
                  >
                    {line}
                  </span>
                ))}
              </div>
            )}

            {filtersPanelOpen && (
              <>
            <div className="mb-4 flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
              <div className="sm:max-w-xs sm:flex-1">
                <label htmlFor="historySearch" className="sr-only">
                  {HISTORY_SEARCH_PLACEHOLDER}
                </label>
                <input
                  id="historySearch"
                  type="text"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                  placeholder={HISTORY_SEARCH_PLACEHOLDER}
                  className="w-full rounded-md border border-zinc-300 bg-white px-3 py-2 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>
              <div className="flex flex-wrap items-center gap-3">
                {/* 「重要のみ表示」フィルタ — すべて/重要のみの2択トグル。
                    検索欄・並び替えの近くに配置する（design:
                    docs/38_history_marking_design.md「9」）。 */}
                <div
                  role="group"
                  aria-label="重要のみ表示"
                  className="inline-flex rounded-md border border-zinc-300 text-xs dark:border-zinc-700"
                >
                  <button
                    type="button"
                    onClick={() => handleImportantFilterChange("all")}
                    aria-pressed={importantFilter === "all"}
                    className={`rounded-l-md px-3 py-1.5 font-medium transition-colors ${
                      importantFilter === "all"
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                        : "bg-white text-zinc-700 hover:bg-zinc-50 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    }`}
                  >
                    {HISTORY_IMPORTANT_FILTER_ALL_LABEL}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleImportantFilterChange("importantOnly")}
                    aria-pressed={importantFilter === "importantOnly"}
                    className={`rounded-r-md border-l border-zinc-300 px-3 py-1.5 font-medium transition-colors dark:border-zinc-700 ${
                      importantFilter === "importantOnly"
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                        : "bg-white text-zinc-700 hover:bg-zinc-50 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    }`}
                  >
                    <span aria-hidden="true">★ </span>
                    {HISTORY_IMPORTANT_FILTER_IMPORTANT_ONLY_LABEL}
                  </button>
                </div>
                {/* 「お気に入りのみ表示」フィルタ (feature/history-favorite-flag)
                    — 重要フラグのトグルと同じ構造、完全に独立した状態。 */}
                <div
                  role="group"
                  aria-label="お気に入りのみ表示"
                  className="inline-flex rounded-md border border-zinc-300 text-xs dark:border-zinc-700"
                >
                  <button
                    type="button"
                    onClick={() => handleFavoriteFilterChange("all")}
                    aria-pressed={favoriteFilter === "all"}
                    className={`rounded-l-md px-3 py-1.5 font-medium transition-colors ${
                      favoriteFilter === "all"
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                        : "bg-white text-zinc-700 hover:bg-zinc-50 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    }`}
                  >
                    {HISTORY_FAVORITE_FILTER_ALL_LABEL}
                  </button>
                  <button
                    type="button"
                    onClick={() => handleFavoriteFilterChange("favoriteOnly")}
                    aria-pressed={favoriteFilter === "favoriteOnly"}
                    className={`rounded-r-md border-l border-zinc-300 px-3 py-1.5 font-medium transition-colors dark:border-zinc-700 ${
                      favoriteFilter === "favoriteOnly"
                        ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                        : "bg-white text-zinc-700 hover:bg-zinc-50 dark:bg-zinc-950 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    }`}
                  >
                    <span aria-hidden="true">♥ </span>
                    {HISTORY_FAVORITE_FILTER_FAVORITE_ONLY_LABEL}
                  </button>
                </div>
                <div className="flex items-center gap-2">
                  <label htmlFor="historySortOrder" className="text-xs text-zinc-500 dark:text-zinc-400">
                    並び替え
                  </label>
                  <select
                    id="historySortOrder"
                    value={sortOrder}
                    onChange={(event) =>
                      handleSortOrderChange(event.target.value as HistorySortOrder)
                    }
                    className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                  >
                    <option value="newest">{HISTORY_SORT_NEWEST_LABEL}</option>
                    <option value="oldest">{HISTORY_SORT_OLDEST_LABEL}</option>
                  </select>
                </div>
              </div>
            </div>

            <div className="mb-4 flex flex-wrap items-end gap-3">
              <div className="flex items-center gap-2">
                <label htmlFor="historyStartedFrom" className="text-xs text-zinc-500 dark:text-zinc-400">
                  開始日
                </label>
                <input
                  id="historyStartedFrom"
                  type="date"
                  value={startedFrom}
                  max={startedTo || undefined}
                  onChange={(event) => handleStartedFromChange(event.target.value)}
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="historyStartedTo" className="text-xs text-zinc-500 dark:text-zinc-400">
                  終了日
                </label>
                <input
                  id="historyStartedTo"
                  type="date"
                  value={startedTo}
                  min={startedFrom || undefined}
                  onChange={(event) => handleStartedToChange(event.target.value)}
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                />
              </div>
            </div>

            {/* AI観測状態フィルター（feature/history-ai-observation-filter）
                — 4つの独立したセレクトボックス。各変更でページ1に戻し、
                既存の検索・重要フラグ・日付範囲とAND条件で組み合わせる。 */}
            <div className="mb-4 flex flex-wrap items-end gap-3">
              <div className="flex items-center gap-2">
                <label htmlFor="historyAiOverviewObservation" className="text-xs text-zinc-500 dark:text-zinc-400">
                  {AI_OVERVIEW_OBSERVATION_FILTER_LABEL_TEXT}
                </label>
                <select
                  id="historyAiOverviewObservation"
                  value={aiOverviewObservation}
                  onChange={(event) =>
                    handleAiOverviewObservationChange(
                      event.target.value as ObservationFilterSelectValue,
                    )
                  }
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  {Object.entries(AI_OVERVIEW_OBSERVATION_FILTER_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="historyChatgptObservation" className="text-xs text-zinc-500 dark:text-zinc-400">
                  {CHATGPT_OBSERVATION_FILTER_LABEL_TEXT}
                </label>
                <select
                  id="historyChatgptObservation"
                  value={chatgptObservation}
                  onChange={(event) =>
                    handleChatgptObservationChange(
                      event.target.value as ObservationFilterSelectValue,
                    )
                  }
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  {Object.entries(SIMPLE_PROVIDER_OBSERVATION_FILTER_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="historyClaudeObservation" className="text-xs text-zinc-500 dark:text-zinc-400">
                  {CLAUDE_OBSERVATION_FILTER_LABEL_TEXT}
                </label>
                <select
                  id="historyClaudeObservation"
                  value={claudeObservation}
                  onChange={(event) =>
                    handleClaudeObservationChange(
                      event.target.value as ObservationFilterSelectValue,
                    )
                  }
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  {Object.entries(SIMPLE_PROVIDER_OBSERVATION_FILTER_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex items-center gap-2">
                <label htmlFor="historyGeminiObservation" className="text-xs text-zinc-500 dark:text-zinc-400">
                  {GEMINI_OBSERVATION_FILTER_LABEL_TEXT}
                </label>
                <select
                  id="historyGeminiObservation"
                  value={geminiObservation}
                  onChange={(event) =>
                    handleGeminiObservationChange(
                      event.target.value as ObservationFilterSelectValue,
                    )
                  }
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  {Object.entries(SIMPLE_PROVIDER_OBSERVATION_FILTER_LABELS).map(([value, label]) => (
                    <option key={value} value={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* カテゴリ/タグフィルタ（feature/history-tags-categories,
                Task 5-C）— 既存フィルタとAND条件で組み合わせる。カテゴリ
                は単一選択（すべて/未分類/各カテゴリ）、タグは複数選択
                可・OR条件（いずれかのタグを持つ履歴に一致）。 */}
            <div className="mb-4 flex flex-wrap items-start gap-4">
              <div className="flex items-center gap-2">
                <label htmlFor="historyCategoryFilter" className="text-xs text-zinc-500 dark:text-zinc-400">
                  {HISTORY_CATEGORY_FILTER_LABEL_TEXT}
                </label>
                <select
                  id="historyCategoryFilter"
                  value={categoryFilter}
                  onChange={(event) =>
                    handleCategoryFilterChange(event.target.value as HistoryCategoryFilterValue)
                  }
                  className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none focus:border-zinc-500 focus:ring-1 focus:ring-zinc-500 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                >
                  <option value={HISTORY_CATEGORY_FILTER_ALL_VALUE}>すべて</option>
                  <option value={HISTORY_CATEGORY_FILTER_UNCATEGORIZED_VALUE}>
                    {UNCATEGORIZED_LABEL}
                  </option>
                  {availableCategories.map((category) => (
                    <option key={category.id} value={category.id}>
                      {category.name}
                    </option>
                  ))}
                </select>
              </div>
              {availableTags.length > 0 && (
                <div className="flex flex-col gap-1">
                  <span className="text-xs text-zinc-500 dark:text-zinc-400">
                    {HISTORY_TAG_FILTER_LABEL_TEXT}
                  </span>
                  <div className="flex flex-wrap gap-1.5">
                    {availableTags.map((tag) => {
                      const selected = selectedTagIds.includes(tag.id);
                      return (
                        <button
                          key={tag.id}
                          type="button"
                          onClick={() => handleTagFilterToggle(tag.id)}
                          aria-pressed={selected}
                          className={`rounded px-2 py-1 text-xs font-medium transition-colors ${
                            selected
                              ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                              : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
                          }`}
                        >
                          {tag.name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              )}
            </div>
              </>
            )}

            <p className="mb-3 text-xs text-zinc-500 dark:text-zinc-400">{paginationLabel}</p>

            {items.length === 0 && (
              <p className="text-sm text-zinc-500 dark:text-zinc-400">
                {emptyResultsText}
              </p>
            )}

            <ul className="space-y-3">
            {items.map((item) => {
              const display = formatAnalysisRunListItem(item);
              const isDeleting = deletingIds.has(item.id);
              const deleteError = deleteErrors[item.id];
              const isImportant = item.isImportant ?? false;
              const importantError = importantErrors[item.id];
              const isFavorite = item.isFavorite ?? false;
              const isFavoriteToggling = favoriteTogglingIds.has(item.id);
              const favoriteError = favoriteErrors[item.id];
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
                      {/* お気に入りbadge — ♥/☆と視覚的に区別するため♥を使用
                          (feature/history-favorite-flag)。重要フラグとは
                          独立して表示/非表示が決まる。 */}
                      {isFavorite && (
                        <span className="rounded bg-rose-100 px-1.5 py-0.5 text-xs font-medium text-rose-700 dark:bg-rose-900/40 dark:text-rose-300">
                          ♥ {HISTORY_FAVORITE_BADGE_LABEL}
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
                  {/* カテゴリ名 + タグbadge（feature/history-tags-
                      categories）— カテゴリは常に1つ表示（未分類含む）、
                      タグは0件のときは何も表示しない。狭い画面でも
                      flex-wrapで折り返すため崩れない。 */}
                  <div className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
                    <span className="max-w-full rounded bg-indigo-100 px-1.5 py-0.5 text-[10px] break-words text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300">
                      {display.categoryLabel}
                    </span>
                    {(item.tags ?? []).map((tag) => (
                      <span
                        key={tag.id}
                        className="max-w-full rounded bg-sky-100 px-1.5 py-0.5 text-[10px] break-words text-sky-700 dark:bg-sky-900/40 dark:text-sky-300"
                      >
                        {tag.name}
                      </span>
                    ))}
                  </div>
                  <div className="mt-3 flex flex-wrap items-center gap-3">
                    <Link
                      href={resolveHistoryListItemDetailPath(item)}
                      className={DETAIL_LINK_BUTTON_CLASSNAME}
                    >
                      {HISTORY_LIST_DETAIL_LINK_TEXT}
                      <span aria-hidden="true">→</span>
                    </Link>
                    {/* queued/runningの間は重要フラグ・削除を出さない —
                        このproject全体に対する既存の削除操作（project
                        membershipで判定、作成者限定ではない）をqueuedな
                        ジョブに使うと、本来は作成者限定であるべきキャン
                        セル相当の効果を誰でも持ててしまう。取り消し操作
                        は`/analysis/jobs/{id}`の専用ボタン（作成者限定）
                        のみを導線とする。failed（既にworkerが再度claim
                        することはない終端状態）は既存のcompleted/partial
                        と同様に扱う。 */}
                    {canManageHistoryListItem(item.status) && (
                      <>
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
                          onClick={() => handleToggleFavorite(item.id, isFavorite)}
                          aria-pressed={isFavorite}
                          disabled={isFavoriteToggling}
                          className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                        >
                          <span aria-hidden="true">{isFavorite ? "♥" : "♡"} </span>
                          {getFavoriteToggleLabel(isFavorite)}
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDelete(item.id)}
                          disabled={isDeleting}
                          className="rounded-md border border-rose-300 px-3 py-1.5 text-xs font-medium text-rose-700 transition-colors hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                        >
                          {isDeleting ? "削除中..." : HISTORY_DELETE_BUTTON_LABEL}
                        </button>
                      </>
                    )}
                  </div>
                  {importantError && (
                    <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                      {importantError}
                    </p>
                  )}
                  {favoriteError && (
                    <p className="mt-2 text-xs text-rose-600 dark:text-rose-400">
                      {favoriteError}
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

            {total > 0 && (
              <div className="mt-6 flex items-center justify-center gap-3">
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.max(1, prev - 1))}
                  disabled={page <= 1}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  前へ
                </button>
                <span className="text-xs text-zinc-500 dark:text-zinc-400">
                  {page} / {totalPages}ページ
                </span>
                <button
                  type="button"
                  onClick={() => setPage((prev) => Math.min(totalPages, prev + 1))}
                  disabled={page >= totalPages}
                  className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                >
                  次へ
                </button>
              </div>
            )}
          </>
        )}
      </main>
    </div>
  );
}
