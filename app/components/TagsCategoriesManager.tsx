"use client";

import { useEffect, useState } from "react";
import {
  CATEGORY_CREATE_BUTTON_LABEL,
  CATEGORY_DELETE_BUTTON_LABEL,
  CATEGORY_DELETE_CONFIRM_MESSAGE,
  CATEGORY_MANAGEMENT_TITLE,
  CATEGORY_NAME_PLACEHOLDER,
  CATEGORY_RENAME_BUTTON_LABEL,
  TAGS_CATEGORIES_NO_PROJECT_MESSAGE,
  TAG_ADD_EXISTING_LABEL,
  TAG_CREATE_BUTTON_LABEL,
  TAG_DELETE_BUTTON_LABEL,
  TAG_DELETE_CONFIRM_MESSAGE,
  TAG_MANAGEMENT_TITLE,
  TAG_NAME_PLACEHOLDER,
  TAG_RENAME_BUTTON_LABEL,
  UNCATEGORIZED_LABEL,
  isValidTagOrCategoryName,
  normalizeTagOrCategoryName,
  resolveAttachTagOutcome,
  resolveCategoryListFetchOutcome,
  resolveCreateCategoryOutcome,
  resolveCreateTagOutcome,
  resolveDeleteCategoryOutcome,
  resolveDeleteTagOutcome,
  resolveDetachTagOutcome,
  resolveRenameCategoryOutcome,
  resolveRenameTagOutcome,
  resolveSetCategoryOutcome,
  resolveTagListFetchOutcome,
} from "../lib/tags-categories";
import type { CategoryItem, TagItem } from "../lib/tags-categories";

export const TAGS_CATEGORIES_SECTION_TITLE = "タグ・カテゴリ";

// `canEdit` mirrors app/lib/analysis-history.ts's canManageHistoryListItem()
// — queued/running runs must not be editable (Task 5-C's "3. 操作性").
// `projectId` undefined means a legacy pre-project run — editing is
// disabled entirely with TAGS_CATEGORIES_NO_PROJECT_MESSAGE rather than
// silently guessing/reusing a different project's id (Task 5-C's "5.
// projectIdの扱い").
type Props = {
  analysisRunId: string;
  projectId: string | undefined;
  canEdit: boolean;
  category: CategoryItem | null | undefined;
  tags: TagItem[] | undefined;
  onCategoryChange: (category: CategoryItem | null) => void;
  onTagsChange: (tags: TagItem[]) => void;
};

export default function TagsCategoriesManager({
  analysisRunId,
  projectId,
  canEdit,
  category,
  tags,
  onCategoryChange,
  onTagsChange,
}: Props) {
  const [availableCategories, setAvailableCategories] = useState<CategoryItem[]>([]);
  const [availableTags, setAvailableTags] = useState<TagItem[]>([]);
  const [optionsError, setOptionsError] = useState<string | undefined>(undefined);

  const [categorySelectBusy, setCategorySelectBusy] = useState(false);
  const [categorySelectError, setCategorySelectError] = useState<string | undefined>(undefined);

  const [newCategoryName, setNewCategoryName] = useState("");
  const [categoryCreateBusy, setCategoryCreateBusy] = useState(false);
  const [categoryCreateError, setCategoryCreateError] = useState<string | undefined>(undefined);

  const [renamingCategoryId, setRenamingCategoryId] = useState<string | null>(null);
  const [renameCategoryDraft, setRenameCategoryDraft] = useState("");
  const [categoryRowBusyId, setCategoryRowBusyId] = useState<string | null>(null);
  const [categoryRowError, setCategoryRowError] = useState<string | undefined>(undefined);

  const [tagToAttach, setTagToAttach] = useState("");
  const [tagAttachBusy, setTagAttachBusy] = useState(false);
  const [tagAttachError, setTagAttachError] = useState<string | undefined>(undefined);
  const [detachingTagId, setDetachingTagId] = useState<string | null>(null);
  const [tagDetachError, setTagDetachError] = useState<string | undefined>(undefined);

  const [newTagName, setNewTagName] = useState("");
  const [tagCreateBusy, setTagCreateBusy] = useState(false);
  const [tagCreateError, setTagCreateError] = useState<string | undefined>(undefined);

  const [renamingTagId, setRenamingTagId] = useState<string | null>(null);
  const [renameTagDraft, setRenameTagDraft] = useState("");
  const [tagRowBusyId, setTagRowBusyId] = useState<string | null>(null);
  const [tagRowError, setTagRowError] = useState<string | undefined>(undefined);

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;

    async function loadOptions() {
      const [tagsResponse, categoriesResponse] = await Promise.all([
        fetch(`/api/tags?projectId=${encodeURIComponent(projectId as string)}`).catch(() => null),
        fetch(`/api/categories?projectId=${encodeURIComponent(projectId as string)}`).catch(
          () => null,
        ),
      ]);
      if (cancelled) return;

      const tagsOutcome = await resolveTagListFetchOutcome(tagsResponse);
      const categoriesOutcome = await resolveCategoryListFetchOutcome(categoriesResponse);
      if (cancelled) return;

      if (tagsOutcome.success) {
        setAvailableTags(tagsOutcome.tags);
      } else {
        setOptionsError(tagsOutcome.message);
      }
      if (categoriesOutcome.success) {
        setAvailableCategories(categoriesOutcome.categories);
      } else {
        setOptionsError(categoriesOutcome.message);
      }
    }

    loadOptions();
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  if (!projectId) {
    return (
      <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
        <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
          {TAGS_CATEGORIES_SECTION_TITLE}
        </h2>
        <p className="mt-2 text-sm text-zinc-500 dark:text-zinc-400">
          {TAGS_CATEGORIES_NO_PROJECT_MESSAGE}
        </p>
      </div>
    );
  }

  const attachedTagIds = new Set((tags ?? []).map((tag) => tag.id));
  const attachableTags = availableTags.filter((tag) => !attachedTagIds.has(tag.id));

  const handleSelectCategory = async (nextCategoryId: string) => {
    setCategorySelectBusy(true);
    setCategorySelectError(undefined);

    const response = await fetch(
      `/api/analysis-runs/${encodeURIComponent(analysisRunId)}/category`,
      {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ categoryId: nextCategoryId === "" ? null : nextCategoryId }),
      },
    ).catch(() => null);
    const outcome = await resolveSetCategoryOutcome(response);

    setCategorySelectBusy(false);
    if (!outcome.success) {
      setCategorySelectError(outcome.message);
      return;
    }

    const next =
      nextCategoryId === ""
        ? null
        : availableCategories.find((c) => c.id === nextCategoryId) ?? null;
    onCategoryChange(next);
  };

  const handleCreateCategory = async () => {
    const name = normalizeTagOrCategoryName(newCategoryName);
    if (!isValidTagOrCategoryName(name)) return;

    setCategoryCreateBusy(true);
    setCategoryCreateError(undefined);

    const response = await fetch("/api/categories", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, name }),
    }).catch(() => null);
    const outcome = await resolveCreateCategoryOutcome(response);

    setCategoryCreateBusy(false);
    if (!outcome.success) {
      setCategoryCreateError(outcome.message);
      return;
    }

    setAvailableCategories((prev) => [...prev, outcome.data]);
    setNewCategoryName("");
    // 作成したカテゴリをすぐこの履歴に設定する — 「頻繁に使う前提で
    // 使いやすく配置する」という要件に沿い、作成後に別途セレクトから
    // 選び直す手間を省く。
    await handleSelectCategory(outcome.data.id);
  };

  const handleStartRenameCategory = (target: CategoryItem) => {
    setRenamingCategoryId(target.id);
    setRenameCategoryDraft(target.name);
    setCategoryRowError(undefined);
  };

  const handleConfirmRenameCategory = async () => {
    if (!renamingCategoryId) return;
    const name = normalizeTagOrCategoryName(renameCategoryDraft);
    if (!isValidTagOrCategoryName(name)) return;

    setCategoryRowBusyId(renamingCategoryId);
    setCategoryRowError(undefined);

    const response = await fetch(`/api/categories/${encodeURIComponent(renamingCategoryId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => null);
    const outcome = await resolveRenameCategoryOutcome(response);

    setCategoryRowBusyId(null);
    if (!outcome.success) {
      setCategoryRowError(outcome.message);
      return;
    }

    setAvailableCategories((prev) =>
      prev.map((c) => (c.id === outcome.data.id ? outcome.data : c)),
    );
    if (category?.id === outcome.data.id) {
      onCategoryChange(outcome.data);
    }
    setRenamingCategoryId(null);
  };

  const handleDeleteCategory = async (target: CategoryItem) => {
    if (!window.confirm(CATEGORY_DELETE_CONFIRM_MESSAGE)) return;

    setCategoryRowBusyId(target.id);
    setCategoryRowError(undefined);

    const response = await fetch(`/api/categories/${encodeURIComponent(target.id)}`, {
      method: "DELETE",
    }).catch(() => null);
    const outcome = await resolveDeleteCategoryOutcome(response);

    setCategoryRowBusyId(null);
    if (!outcome.success) {
      setCategoryRowError(outcome.message);
      return;
    }

    setAvailableCategories((prev) => prev.filter((c) => c.id !== target.id));
    // バックエンドのON DELETE SET NULLにより、このカテゴリを使っていた
    // すべての履歴（この履歴を含む）は未分類に戻る。
    if (category?.id === target.id) {
      onCategoryChange(null);
    }
  };

  const handleAttachTag = async () => {
    if (!tagToAttach) return;

    setTagAttachBusy(true);
    setTagAttachError(undefined);

    const response = await fetch(
      `/api/analysis-runs/${encodeURIComponent(analysisRunId)}/tags`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ tagId: tagToAttach }),
      },
    ).catch(() => null);
    const outcome = await resolveAttachTagOutcome(response);

    setTagAttachBusy(false);
    if (!outcome.success) {
      setTagAttachError(outcome.message);
      return;
    }

    const attached = availableTags.find((tag) => tag.id === tagToAttach);
    if (attached) {
      onTagsChange([...(tags ?? []), attached]);
    }
    setTagToAttach("");
  };

  const handleDetachTag = async (tagId: string) => {
    setDetachingTagId(tagId);
    setTagDetachError(undefined);

    const response = await fetch(
      `/api/analysis-runs/${encodeURIComponent(analysisRunId)}/tags/${encodeURIComponent(tagId)}`,
      { method: "DELETE" },
    ).catch(() => null);
    const outcome = await resolveDetachTagOutcome(response);

    setDetachingTagId(null);
    if (!outcome.success) {
      setTagDetachError(outcome.message);
      return;
    }

    onTagsChange((tags ?? []).filter((tag) => tag.id !== tagId));
  };

  const handleCreateTag = async () => {
    const name = normalizeTagOrCategoryName(newTagName);
    if (!isValidTagOrCategoryName(name)) return;

    setTagCreateBusy(true);
    setTagCreateError(undefined);

    const response = await fetch("/api/tags", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ projectId, name }),
    }).catch(() => null);
    const outcome = await resolveCreateTagOutcome(response);

    setTagCreateBusy(false);
    if (!outcome.success) {
      setTagCreateError(outcome.message);
      return;
    }

    setAvailableTags((prev) => [...prev, outcome.data]);
    setNewTagName("");
  };

  const handleStartRenameTag = (target: TagItem) => {
    setRenamingTagId(target.id);
    setRenameTagDraft(target.name);
    setTagRowError(undefined);
  };

  const handleConfirmRenameTag = async () => {
    if (!renamingTagId) return;
    const name = normalizeTagOrCategoryName(renameTagDraft);
    if (!isValidTagOrCategoryName(name)) return;

    setTagRowBusyId(renamingTagId);
    setTagRowError(undefined);

    const response = await fetch(`/api/tags/${encodeURIComponent(renamingTagId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    }).catch(() => null);
    const outcome = await resolveRenameTagOutcome(response);

    setTagRowBusyId(null);
    if (!outcome.success) {
      setTagRowError(outcome.message);
      return;
    }

    setAvailableTags((prev) => prev.map((tag) => (tag.id === outcome.data.id ? outcome.data : tag)));
    onTagsChange((tags ?? []).map((tag) => (tag.id === outcome.data.id ? outcome.data : tag)));
    setRenamingTagId(null);
  };

  const handleDeleteTag = async (target: TagItem) => {
    if (!window.confirm(TAG_DELETE_CONFIRM_MESSAGE)) return;

    setTagRowBusyId(target.id);
    setTagRowError(undefined);

    const response = await fetch(`/api/tags/${encodeURIComponent(target.id)}`, {
      method: "DELETE",
    }).catch(() => null);
    const outcome = await resolveDeleteTagOutcome(response);

    setTagRowBusyId(null);
    if (!outcome.success) {
      setTagRowError(outcome.message);
      return;
    }

    setAvailableTags((prev) => prev.filter((tag) => tag.id !== target.id));
    // バックエンドのON DELETE CASCADEにより、このタグはすべての履歴
    // （この履歴を含む）から解除される。
    onTagsChange((tags ?? []).filter((tag) => tag.id !== target.id));
  };

  return (
    <div className="rounded-lg border border-zinc-200 bg-white p-5 shadow-sm dark:border-zinc-800 dark:bg-zinc-900">
      <h2 className="text-sm font-semibold text-zinc-900 dark:text-zinc-50">
        {TAGS_CATEGORIES_SECTION_TITLE}
      </h2>
      {!canEdit && (
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          この分析はまだ実行中のため、タグ・カテゴリを編集できません。
        </p>
      )}
      {optionsError && (
        <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{optionsError}</p>
      )}

      {/* --- カテゴリ --- */}
      <div className="mt-4">
        <h3 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
          {CATEGORY_MANAGEMENT_TITLE}
        </h3>
        <p className="mt-1 text-sm text-zinc-900 dark:text-zinc-50">
          現在のカテゴリ: {category?.name ?? UNCATEGORIZED_LABEL}
        </p>
        <div className="mt-2 flex items-center gap-2">
          <select
            value={category?.id ?? ""}
            disabled={!canEdit || categorySelectBusy}
            onChange={(event) => handleSelectCategory(event.target.value)}
            className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
          >
            <option value="">{UNCATEGORIZED_LABEL}</option>
            {availableCategories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
        {categorySelectError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{categorySelectError}</p>
        )}

        {canEdit && (
          <div className="mt-3 flex items-center gap-2">
            <input
              type="text"
              value={newCategoryName}
              onChange={(event) => setNewCategoryName(event.target.value)}
              placeholder={CATEGORY_NAME_PLACEHOLDER}
              disabled={categoryCreateBusy}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
            />
            <button
              type="button"
              onClick={handleCreateCategory}
              disabled={categoryCreateBusy || !isValidTagOrCategoryName(newCategoryName)}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              {CATEGORY_CREATE_BUTTON_LABEL}
            </button>
          </div>
        )}
        {categoryCreateError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{categoryCreateError}</p>
        )}

        {canEdit && availableCategories.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {availableCategories.map((c) => (
              <li key={c.id} className="flex items-center gap-2 text-xs">
                {renamingCategoryId === c.id ? (
                  <>
                    <input
                      type="text"
                      value={renameCategoryDraft}
                      onChange={(event) => setRenameCategoryDraft(event.target.value)}
                      disabled={categoryRowBusyId === c.id}
                      className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 shadow-sm outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                    />
                    <button
                      type="button"
                      onClick={handleConfirmRenameCategory}
                      disabled={
                        categoryRowBusyId === c.id ||
                        !isValidTagOrCategoryName(renameCategoryDraft)
                      }
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingCategoryId(null)}
                      disabled={categoryRowBusyId === c.id}
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-300">
                      {c.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleStartRenameCategory(c)}
                      disabled={categoryRowBusyId === c.id}
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      {CATEGORY_RENAME_BUTTON_LABEL}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteCategory(c)}
                      disabled={categoryRowBusyId === c.id}
                      className="rounded-md border border-rose-300 px-2 py-1 font-medium text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                    >
                      {CATEGORY_DELETE_BUTTON_LABEL}
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {categoryRowError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{categoryRowError}</p>
        )}
      </div>

      {/* --- タグ --- */}
      <div className="mt-6">
        <h3 className="text-xs font-semibold text-zinc-700 dark:text-zinc-300">
          {TAG_MANAGEMENT_TITLE}
        </h3>
        <div className="mt-1 flex flex-wrap gap-1.5">
          {(tags ?? []).length === 0 && (
            <span className="text-sm text-zinc-500 dark:text-zinc-400">タグなし</span>
          )}
          {(tags ?? []).map((tag) => (
            <span
              key={tag.id}
              className="inline-flex items-center gap-1 rounded bg-sky-100 px-1.5 py-0.5 text-xs text-sky-700 dark:bg-sky-900/40 dark:text-sky-300"
            >
              {tag.name}
              {canEdit && (
                <button
                  type="button"
                  onClick={() => handleDetachTag(tag.id)}
                  disabled={detachingTagId === tag.id}
                  aria-label={`${tag.name}を解除`}
                  className="disabled:cursor-not-allowed disabled:opacity-50"
                >
                  ✕
                </button>
              )}
            </span>
          ))}
        </div>
        {tagDetachError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{tagDetachError}</p>
        )}

        {canEdit && attachableTags.length > 0 && (
          <div className="mt-2 flex items-center gap-2">
            <select
              value={tagToAttach}
              onChange={(event) => setTagToAttach(event.target.value)}
              disabled={tagAttachBusy}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
            >
              <option value="">{TAG_ADD_EXISTING_LABEL}</option>
              {attachableTags.map((tag) => (
                <option key={tag.id} value={tag.id}>
                  {tag.name}
                </option>
              ))}
            </select>
            <button
              type="button"
              onClick={handleAttachTag}
              disabled={tagAttachBusy || !tagToAttach}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              追加
            </button>
          </div>
        )}
        {tagAttachError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{tagAttachError}</p>
        )}

        {canEdit && (
          <div className="mt-3 flex items-center gap-2">
            <input
              type="text"
              value={newTagName}
              onChange={(event) => setNewTagName(event.target.value)}
              placeholder={TAG_NAME_PLACEHOLDER}
              disabled={tagCreateBusy}
              className="rounded-md border border-zinc-300 bg-white px-2 py-1.5 text-sm text-zinc-900 shadow-sm outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
            />
            <button
              type="button"
              onClick={handleCreateTag}
              disabled={tagCreateBusy || !isValidTagOrCategoryName(newTagName)}
              className="rounded-md border border-zinc-300 px-3 py-1.5 text-xs font-medium text-zinc-700 transition-colors hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
            >
              {TAG_CREATE_BUTTON_LABEL}
            </button>
          </div>
        )}
        {tagCreateError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{tagCreateError}</p>
        )}

        {canEdit && availableTags.length > 0 && (
          <ul className="mt-3 space-y-1.5">
            {availableTags.map((tag) => (
              <li key={tag.id} className="flex items-center gap-2 text-xs">
                {renamingTagId === tag.id ? (
                  <>
                    <input
                      type="text"
                      value={renameTagDraft}
                      onChange={(event) => setRenameTagDraft(event.target.value)}
                      disabled={tagRowBusyId === tag.id}
                      className="rounded-md border border-zinc-300 bg-white px-2 py-1 text-xs text-zinc-900 shadow-sm outline-none disabled:opacity-50 dark:border-zinc-700 dark:bg-zinc-950 dark:text-zinc-50"
                    />
                    <button
                      type="button"
                      onClick={handleConfirmRenameTag}
                      disabled={tagRowBusyId === tag.id || !isValidTagOrCategoryName(renameTagDraft)}
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      onClick={() => setRenamingTagId(null)}
                      disabled={tagRowBusyId === tag.id}
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      取消
                    </button>
                  </>
                ) : (
                  <>
                    <span className="min-w-0 flex-1 truncate text-zinc-700 dark:text-zinc-300">
                      {tag.name}
                    </span>
                    <button
                      type="button"
                      onClick={() => handleStartRenameTag(tag)}
                      disabled={tagRowBusyId === tag.id}
                      className="rounded-md border border-zinc-300 px-2 py-1 font-medium text-zinc-700 hover:bg-zinc-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-zinc-700 dark:text-zinc-300 dark:hover:bg-zinc-900"
                    >
                      {TAG_RENAME_BUTTON_LABEL}
                    </button>
                    <button
                      type="button"
                      onClick={() => handleDeleteTag(tag)}
                      disabled={tagRowBusyId === tag.id}
                      className="rounded-md border border-rose-300 px-2 py-1 font-medium text-rose-700 hover:bg-rose-50 disabled:cursor-not-allowed disabled:opacity-50 dark:border-rose-800 dark:text-rose-400 dark:hover:bg-rose-950"
                    >
                      {TAG_DELETE_BUTTON_LABEL}
                    </button>
                  </>
                )}
              </li>
            ))}
          </ul>
        )}
        {tagRowError && (
          <p className="mt-1 text-xs text-rose-600 dark:text-rose-400">{tagRowError}</p>
        )}
      </div>
    </div>
  );
}
